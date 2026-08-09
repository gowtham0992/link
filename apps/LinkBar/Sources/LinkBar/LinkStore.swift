import AppKit
import Foundation
import ServiceManagement
import SwiftUI

/// App state: review inbox, capture inbox, recent activity, quick recall —
/// all refreshed from the CLI's --json output. The workspace directories are
/// watched directly, so the badge updates the moment a session hook writes a
/// capture — no polling delay.
@MainActor
final class LinkStore: ObservableObject {
    enum FlashTone { case success, info }

    @Published var inbox: MemoryInbox?
    @Published var captures: CaptureInbox?
    @Published var activity: [LogEntry] = []
    @Published var recallResults: [RecalledMemory] = []
    @Published var searchedQuery: String?
    @Published var abstention: Abstention?
    @Published var lastError: String?
    @Published var flash: String?
    @Published var flashTone: FlashTone = .success
    @Published var busy = false
    @Published var linkVersion: String = ""
    @Published var stats: StatusPayload?
    @Published var digest: DigestPayload?
    @Published var syncState: SyncStatus?
    @Published var handoffsWaiting: [HandoffsPayload.Handoff] = []
    @Published var runtimeWarning: String?
    @Published var launchAtLogin: Bool = SMAppService.mainApp.status == .enabled

    // Status dashboard: the health of every Link surface.
    @Published var mcp: MCPVerify?
    @Published var semantic: SemanticStatus?
    @Published var claudeHooksWired: Bool?
    @Published var viewerRunning = false
    @Published var activeSessions: [AgentSession] = []
    @Published var memories: [MemoryPage] = []
    /// explain-memory payloads keyed by memory name, fetched on row expand.
    @Published var explanations: [String: MemoryExplanation] = [:]
    private var lastHealthAt = Date.distantPast

    var pendingCount: Int {
        (inbox?.reviewCount ?? 0) + (captures?.count ?? 0)
    }

    /// Memory writes per day for the last `days` days (today last) —
    /// derived from the log, no extra CLI call.
    func activityPulse(days: Int = 14) -> [Int] {
        var buckets = [Int](repeating: 0, count: days)
        let calendar = Calendar.current
        let today = calendar.startOfDay(for: Date())
        for entry in activity {
            guard let date = entry.date else { continue }
            let delta = calendar.dateComponents([.day], from: calendar.startOfDay(for: date), to: today).day ?? .max
            if delta >= 0 && delta < days {
                buckets[days - 1 - delta] += 1
            }
        }
        return buckets
    }

    private var timer: Timer?
    private var watchers: [DirectoryWatcher] = []
    private var refreshDebounce: DispatchWorkItem?
    private var flashGeneration = 0
    private var started = false

    func start() {
        // The popover calls this on every open; guard so timers and
        // watchers are created exactly once per app lifetime.
        if started { refresh(); return }
        started = true
        refresh()
        // Fallback heartbeat only — the directory watchers do the real work.
        timer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        startWatching()
    }

    /// Watch the paths that change when memory changes: captures land in
    /// raw/memory-captures, memories in wiki/memories, log in wiki.
    private var watchPaths: [String] {
        let root = LinkCLI.workspace
        return [
            root,
            (root as NSString).appendingPathComponent("raw/memory-captures"),
            (root as NSString).appendingPathComponent("raw/handoffs"),
            (root as NSString).appendingPathComponent("wiki/memories"),
            (root as NSString).appendingPathComponent("wiki"),
        ]
    }

    private func startWatching() {
        watchers = watchPaths.compactMap { path in
            DirectoryWatcher(path: path) { [weak self] in
                Task { @MainActor in self?.scheduleRefresh() }
            }
        }
    }

    /// A fresh workspace may not have raw/memory-captures yet, so its
    /// watcher fails at launch; once the first capture creates the
    /// directory, pick it up instead of staying blind until restart.
    private func healWatchersIfNeeded() {
        guard watchers.count < watchPaths.count else { return }
        startWatching()
    }

    /// Coalesce watcher bursts (a single accept touches several files).
    private func scheduleRefresh() {
        refreshDebounce?.cancel()
        let work = DispatchWorkItem { [weak self] in
            Task { @MainActor in self?.refresh() }
        }
        refreshDebounce = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6, execute: work)
    }

    func refresh() {
        busy = true
        Task.detached(priority: .userInitiated) {
            let workspace = LinkCLI.workspace
            let inbox = try? LinkCLI.runJSON(MemoryInbox.self, ["memory-inbox", workspace, "--json"])
            // --proposals ships with lnk 2.2.1; against an older CLI the flag
            // is an argparse error, so fall back to the capped preview rather
            // than showing an empty inbox on version skew.
            let captures = (try? LinkCLI.runJSON(CaptureInbox.self, ["capture-inbox", workspace, "--json", "--proposals", "50"]))
                ?? (try? LinkCLI.runJSON(CaptureInbox.self, ["capture-inbox", workspace, "--json"]))
            let log = try? LinkCLI.runJSON(MemoryLog.self, ["memory-log", workspace, "--json", "--limit", "200"])
            let status = try? LinkCLI.runJSON(StatusPayload.self, ["status", workspace, "--json"])
            let handoffs = try? LinkCLI.runJSON(HandoffsPayload.self, ["handoffs", workspace, "--json"])
            let sessions = Self.scanAgentSessions()
            let memories = MemoryPage.load(from: workspace)
            await MainActor.run {
                self.activeSessions = sessions
                self.memories = memories
                if inbox == nil && captures == nil {
                    self.lastError = "Could not reach lnk — is Link installed? (brew install gowtham0992/link/link)"
                } else {
                    self.lastError = nil
                }
                self.handoffsWaiting = handoffs?.handoffs ?? self.handoffsWaiting
                self.inbox = inbox ?? self.inbox
                self.captures = captures ?? self.captures
                self.activity = log.map { Array($0.entries.reversed()) } ?? self.activity
                if let status {
                    self.stats = status
                    self.linkVersion = status.version ?? self.linkVersion
                    self.runtimeWarning = status.warnings?
                        .first { $0.code == "stale_runtime" }?
                        .message
                }
                self.busy = false
                self.healWatchersIfNeeded()
                if let caps = self.captures?.captures {
                    NotificationManager.shared.announceNewCaptures(caps)
                }
            }
            // Health surfaces are heavier (each spawns a Python probe), so
            // refresh them at most every 15s and after the fast data is on
            // screen — the dots fill in a moment later without blocking.
            await self.refreshHealthIfDue()
        }
    }

    /// Force a health refresh now (used by the manual refresh button and
    /// when the Status tab opens).
    func refreshHealth() {
        Task.detached(priority: .utility) { await self.fetchHealth() }
    }

    private func refreshHealthIfDue() async {
        let due = await MainActor.run { Date().timeIntervalSince(self.lastHealthAt) > 15 }
        if due { await fetchHealth() }
    }

    private func fetchHealth() async {
        let workspace = LinkCLI.workspace
        let mcp = try? LinkCLI.runJSON(MCPVerify.self, ["verify-mcp", workspace, "--json"])
        let semantic = try? LinkCLI.runJSON(SemanticStatus.self, ["semantic", workspace, "--json"])
        let hooks = Self.claudeHooksAreWired()
        let viewer = await Self.viewerResponds()
        let digest = try? LinkCLI.runJSON(DigestPayload.self, ["digest", workspace, "--json"])
        let syncState = try? LinkCLI.runJSON(SyncStatus.self, ["sync", workspace, "--status", "--json"])
        await MainActor.run {
            self.mcp = mcp ?? self.mcp
            self.semantic = semantic ?? self.semantic
            self.digest = digest ?? self.digest
            self.syncState = syncState ?? self.syncState
            if let digest { NotificationManager.shared.announceWeeklyDigest(digest) }
            self.claudeHooksWired = hooks
            self.viewerRunning = viewer
            self.lastHealthAt = Date()
        }
    }

    /// Detect live agent sessions: a Claude Code project whose newest
    /// transcript was written in the last 5 minutes is "active now".
    /// (Transcripts stream continuously while a session runs.) Codex/Cursor
    /// roots can join this scan later.
    nonisolated private static func scanAgentSessions(activeWindow: TimeInterval = 300) -> [AgentSession] {
        let fm = FileManager.default
        let root = (NSHomeDirectory() as NSString).appendingPathComponent(".claude/projects")
        guard let projects = try? fm.contentsOfDirectory(atPath: root) else { return [] }
        var found: [AgentSession] = []
        let now = Date()
        for slug in projects where !slug.hasPrefix(".") {
            let dir = (root as NSString).appendingPathComponent(slug)
            guard let files = try? fm.contentsOfDirectory(atPath: dir) else { continue }
            var newest = Date.distantPast
            for f in files where f.hasSuffix(".jsonl") {
                let path = (dir as NSString).appendingPathComponent(f)
                if let m = (try? fm.attributesOfItem(atPath: path))?[.modificationDate] as? Date, m > newest {
                    newest = m
                }
            }
            if now.timeIntervalSince(newest) < activeWindow {
                // Slug is the full path with dashes; the tail is the repo name.
                let project = slug.split(separator: "-").last.map(String.init) ?? slug
                found.append(AgentSession(project: project, lastActive: newest))
            }
        }
        return found.sorted { $0.lastActive > $1.lastActive }
    }

    /// Read Claude Code's settings.json directly to see whether Link's
    /// session hooks are wired (the flagship agent; other agents live in
    /// their own configs and are added as the dashboard grows).
    nonisolated private static func claudeHooksAreWired() -> Bool {
        let path = (NSHomeDirectory() as NSString).appendingPathComponent(".claude/settings.json")
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return false }
        return text.contains("SessionStart") && text.contains("hook session-start")
    }

    /// The live dashboard rows, most-critical surfaces first.

    /// "git@github.com:user/link-memory.git" -> "user/link-memory".
    private func shortRemote(_ remote: String?) -> String {
        guard var text = remote, !text.isEmpty else { return "remote" }
        if text.hasSuffix(".git") { text = String(text.dropLast(4)) }
        if let colon = text.lastIndex(of: ":"), text.contains("@") {
            return String(text[text.index(after: colon)...])
        }
        let parts = text.split(separator: "/")
        return parts.count >= 2 ? parts.suffix(2).joined(separator: "/") : text
    }

    func surfaces() -> [SurfaceHealth] {
        var rows: [SurfaceHealth] = []

        // CLI
        if linkVersion.isEmpty && lastError != nil {
            rows.append(.init(icon: "terminal", name: "CLI", level: .error,
                              detail: "lnk not found on PATH",
                              fix: .init(label: "Install") { [weak self] in self?.openInstallDocs() }))
        } else {
            rows.append(.init(icon: "terminal", name: "CLI", level: .ok,
                              detail: linkVersion.isEmpty ? "installed" : "lnk \(linkVersion)"))
        }

        // Workspace
        if runtimeWarning != nil {
            rows.append(.init(icon: "shippingbox", name: "Workspace", level: .warn,
                              detail: "runtime is stale — recall may use old logic",
                              fix: .init(label: "Refresh") { [weak self] in self?.repairRuntime() }))
        } else if let s = stats {
            let review = s.needsReviewCount ?? 0
            let level: SurfaceHealth.Level = review > 0 ? .info : .ok
            let counts = "\(s.activeMemoryCount ?? 0) active · \(s.contentPageCount ?? 0) pages"
            rows.append(.init(icon: "shippingbox", name: "Workspace", level: level,
                              detail: review > 0 ? "\(counts) · \(review) to review" : counts))
        } else {
            rows.append(.init(icon: "shippingbox", name: "Workspace", level: .info, detail: "checking…"))
        }

        // MCP
        if let m = mcp {
            if m.ready {
                rows.append(.init(icon: "point.3.connected.trianglepath.dotted", name: "MCP", level: .ok,
                                  detail: "ready · link-mcp \(m.linkMcp?.version ?? "?")"))
            } else if m.linkMcp?.installed != true {
                rows.append(.init(icon: "point.3.connected.trianglepath.dotted", name: "MCP", level: .error,
                                  detail: "server not provisioned",
                                  fix: .init(label: "Repair") { [weak self] in self?.repairRuntime() }))
            } else {
                let want = m.expectedVersion ?? "?"
                rows.append(.init(icon: "point.3.connected.trianglepath.dotted", name: "MCP", level: .warn,
                                  detail: "version \(m.linkMcp?.version ?? "?") ≠ Link \(want)",
                                  fix: .init(label: "Fix") { [weak self] in self?.upgradeMCP() }))
            }
        } else {
            rows.append(.init(icon: "point.3.connected.trianglepath.dotted", name: "MCP", level: .info, detail: "checking…"))
        }

        // Hooks (Claude Code)
        switch claudeHooksWired {
        case .some(true):
            rows.append(.init(icon: "bolt.horizontal", name: "Hooks", level: .ok,
                              detail: "Claude Code: session capture wired"))
        case .some(false):
            rows.append(.init(icon: "bolt.horizontal", name: "Hooks", level: .warn,
                              detail: "Claude Code: not wired — no automatic capture",
                              fix: .init(label: "Wire") { [weak self] in self?.wireClaudeHooks() }))
        case .none:
            rows.append(.init(icon: "bolt.horizontal", name: "Hooks", level: .info, detail: "checking…"))
        }

        // Memory in use — the honest answer to "are my agents reading this?"
        if let usage = digest?.usage {
            if !usage.tracking {
                rows.append(.init(icon: "waveform.path.ecg", name: "Memory in use", level: .info,
                                  detail: "retrieval tracking is off (LINK_USAGE=off)"))
            } else if !usage.hasData {
                rows.append(.init(icon: "waveform.path.ecg", name: "Memory in use", level: .info,
                                  detail: "no reads recorded yet — start a session"))
            } else {
                let window = digest?.windowDays ?? 7
                var detail = "\(usage.retrievals) read(s) · \(usage.briefs) brief(s) in \(window)d"
                if usage.neverRetrievedCount > 0 {
                    detail += " · \(usage.neverRetrievedCount) never used"
                }
                let top = (usage.topMemories ?? []).prefix(3).map { "\($0.memory) · \($0.times)\u{00D7}" }
                rows.append(.init(icon: "waveform.path.ecg", name: "Memory in use",
                                  level: usage.retrievals > 0 ? .ok : .warn, detail: detail,
                                  sub: Array(top)))
            }
        }

        // Sync — only shown once the workspace is a sync repo; a
        // non-syncing local workspace is a fine steady state, not a warning.
        if let sync = syncState, sync.ready {
            let ahead = sync.ahead ?? 0
            let behind = sync.behind ?? 0
            var detail = shortRemote(sync.remote)
            if ahead == 0 && behind == 0 && sync.dirty != true {
                detail += " · in sync"
            } else {
                if ahead > 0 { detail += " · \(ahead) to push" }
                if behind > 0 { detail += " · \(behind) to pull" }
                if sync.dirty == true { detail += " · local changes" }
            }
            rows.append(.init(icon: "arrow.triangle.2.circlepath", name: "Sync",
                              level: behind > 0 ? .warn : .ok, detail: detail))
        }

        // Recall power (semantic tier)
        if let sem = semantic {
            if sem.enabled, let tier = sem.tier {
                // `tier` is a full descriptive sentence ("fast (static
                // embeddings; instant load, …)"); the row wants the tier
                // name only, or .capitalized title-cases the whole thing.
                let name = tier.split(separator: " ").first.map(String.init) ?? tier
                let rerank = (sem.rerankReady == true) ? " + rerank" : ""
                rows.append(.init(icon: "sparkle.magnifyingglass", name: "Recall", level: .ok,
                                  detail: "\(name.capitalized) tier\(rerank) · \(sem.provider ?? "semantic")"))
            } else {
                rows.append(.init(icon: "sparkle.magnifyingglass", name: "Recall", level: .info,
                                  detail: "Lexical only — no semantic matching yet",
                                  fix: .init(label: "Enable") { [weak self] in self?.setupSemantic() }))
            }
        } else {
            rows.append(.init(icon: "sparkle.magnifyingglass", name: "Recall", level: .info, detail: "checking…"))
        }

        // Viewer
        rows.append(.init(icon: "gauge.with.needle", name: "Viewer",
                          level: viewerRunning ? .ok : .info,
                          detail: viewerRunning ? "running · 127.0.0.1:3000" : "not running",
                          fix: viewerRunning ? nil : .init(label: "Open") { [weak self] in self?.openDashboard() }))

        return rows
    }

    /// Any surface that a user would want to act on (amber menu-bar dot).
    var anyUnhealthy: Bool {
        surfaces().contains { $0.level == .warn || $0.level == .error }
    }

    // MARK: Memory Palette (global-hotkey recall/remember)

    /// Palette recall: returns results to a callback without disturbing the
    /// popover's own recall state.
    func paletteRecall(_ query: String, then: @escaping ([RecalledMemory], Abstention?) -> Void) {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { then([], nil); return }
        Task.detached(priority: .userInitiated) {
            let payload = try? LinkCLI.runJSON(RecallPayload.self, ["recall", q, LinkCLI.workspace, "--json"])
            await MainActor.run { then(payload?.memories ?? [], payload?.abstention) }
        }
    }

    /// Palette remember: review-gated write, result to a callback so the
    /// floating panel can confirm inline (its flash is offscreen).
    func paletteRemember(_ text: String, then: @escaping (RememberResult?) -> Void) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { then(nil); return }
        let bounded = String(trimmed.prefix(2000))
        Task.detached(priority: .userInitiated) {
            let result = try? LinkCLI.runJSON(RememberResult.self, ["remember", bounded, LinkCLI.workspace, "--json"])
            await MainActor.run { self.refresh(); then(result) }
        }
    }

    func recall(_ query: String) {
        guard !query.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        busy = true
        Task.detached(priority: .userInitiated) {
            do {
                let payload = try LinkCLI.runJSON(
                    RecallPayload.self,
                    ["recall", query, LinkCLI.workspace, "--json"]
                )
                await MainActor.run {
                    self.recallResults = payload.memories
                    self.abstention = payload.abstention
                    self.searchedQuery = query
                    self.busy = false
                }
            } catch {
                await MainActor.run {
                    self.lastError = String(describing: error)
                    self.busy = false
                }
            }
        }
    }

    /// Approve: mark the memory reviewed. The gate, one click.
    func markReviewed(_ item: InboxItem) {
        act(["review-memory", item.name, LinkCLI.workspace])
    }

    /// Reject: archive the memory (never silent deletion).
    func archive(_ item: InboxItem) {
        act(["archive-memory", item.name, LinkCLI.workspace])
    }

    /// Accept a session capture proposal into the reviewed memory flow.
    func acceptCapture(_ capture: CaptureItem, index: Int = 1) {
        act(["accept-capture", capture.path, LinkCLI.workspace, "--index", "\(index)"])
    }

    /// Why does Link believe this? Lazily fetched per memory when the row
    /// expands; cached until the next refresh cycle replaces memories.
    func explainMemory(named name: String) {
        guard explanations[name] == nil else { return }
        Task.detached(priority: .userInitiated) {
            let payload = try? LinkCLI.runJSON(
                MemoryExplanation.self,
                ["explain-memory", name, LinkCLI.workspace, "--json"]
            )
            await MainActor.run {
                if let payload { self.explanations[name] = payload }
            }
        }
    }

    /// Archive/restore straight from the memory browser.
    func archiveMemory(named name: String) {
        act(["archive-memory", name, LinkCLI.workspace])
    }

    func restoreMemory(named name: String) {
        act(["restore-memory", name, LinkCLI.workspace])
    }

    /// Accept a capture from a notification banner (path only, first proposal).
    func acceptCaptureByPath(_ path: String) {
        act(["accept-capture", path, LinkCLI.workspace, "--index", "1"])
        showFlash("Accepted from notification.", tone: .success)
    }

    func deleteCapture(_ capture: CaptureItem) {
        act(["delete-capture", capture.path, LinkCLI.workspace, "--confirm"])
    }

    /// Collapse inbox captures that offer nothing new (already pending in a
    /// newer capture, accepted as memory, or previously dismissed). Outcome
    /// comes from the command's own JSON, never assumed from exit 0.
    /// The next session resumed the handoff; clear it from every surface.
    func clearHandoff(_ handoff: HandoffsPayload.Handoff) {
        busy = true
        Task.detached(priority: .userInitiated) {
            _ = try? LinkCLI.runRaw(["handoffs", LinkCLI.workspace, "--clear", handoff.file])
            await MainActor.run {
                self.showFlash("Handoff cleared.", tone: .success)
                self.refresh()
            }
        }
    }

    func dedupCaptures() {
        busy = true
        Task.detached(priority: .userInitiated) {
            do {
                let result = try LinkCLI.runJSON(
                    DedupCapturesResult.self,
                    ["dedup-captures", LinkCLI.workspace, "--confirm", "--json"]
                )
                await MainActor.run {
                    if result.removed.isEmpty {
                        // A full inbox with nothing redundant means the work
                        // is review, not cleanup — say so instead of leaving
                        // the user with a button that "did nothing".
                        let waiting = self.captures?.count ?? 0
                        if waiting > 0 {
                            self.showFlash("Nothing redundant — these \(waiting) need review: expand a capture to accept or dismiss its proposals.", tone: .info)
                        } else {
                            self.showFlash("Inbox is clear.", tone: .success)
                        }
                        self.busy = false
                    } else {
                        self.showFlash("Removed \(result.removed.count) redundant capture\(result.removed.count == 1 ? "" : "s").", tone: .success)
                        self.refresh()
                    }
                }
            } catch {
                await MainActor.run {
                    self.lastError = String(describing: error)
                    self.busy = false
                }
            }
        }
    }

    /// Save typed text as a memory — review-gated like every other write.
    func rememberText(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            showFlash("Nothing to remember — type something first.", tone: .info)
            return
        }
        let bounded = String(trimmed.prefix(2000))
        busy = true
        Task.detached(priority: .userInitiated) {
            do {
                let result = try LinkCLI.runJSON(
                    RememberResult.self,
                    ["remember", bounded, LinkCLI.workspace, "--json"]
                )
                await MainActor.run {
                    if result.created {
                        self.showFlash("Saved — pending your review.", tone: .success)
                    } else if result.secret == true {
                        self.showFlash("Not saved — that looks like a secret. Use a password manager.", tone: .info)
                        self.busy = false
                    } else {
                        self.showFlash("Not saved — a similar or conflicting memory exists.", tone: .info)
                        self.busy = false
                    }
                    self.refresh()
                }
            } catch {
                await MainActor.run {
                    self.lastError = String(describing: error)
                    self.busy = false
                }
            }
        }
    }

    /// Save the clipboard as a memory — review-gated like every other write.
    func rememberClipboard() {
        guard let text = NSPasteboard.general.string(forType: .string)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            !text.isEmpty
        else {
            showFlash("Clipboard has no text.", tone: .info)
            return
        }
        rememberText(text)
    }

    /// Refresh the workspace runtime copy (the stale_runtime repair).
    func repairRuntime() {
        busy = true
        Task.detached(priority: .userInitiated) {
            do {
                _ = try LinkCLI.run(["init", LinkCLI.workspace])
                await MainActor.run {
                    self.showFlash("Workspace runtime refreshed.", tone: .success)
                    self.runtimeWarning = nil
                    self.refresh()
                }
            } catch {
                await MainActor.run {
                    self.lastError = String(describing: error)
                    self.busy = false
                }
            }
        }
    }

    // MARK: Status-dashboard remediations

    /// Install the semantic tier into the managed venv and fetch the model
    /// (the only network step Link takes, with the user's click as consent).
    ///
    /// `--setup` only actually provisions on Link 1.7+; older CLIs just print
    /// the manual pip steps. So we verify the *outcome* (re-read semantic
    /// --json) rather than trusting the exit code, and flash the truth.
    func setupSemantic() {
        busy = true
        showFlash("Setting up semantic recall…", tone: .info)
        Task.detached(priority: .userInitiated) {
            _ = try? LinkCLI.run(["semantic", LinkCLI.workspace, "--setup"])
            let after = try? LinkCLI.runJSON(SemanticStatus.self, ["semantic", LinkCLI.workspace, "--json"])
            await MainActor.run {
                self.busy = false
                self.semantic = after ?? self.semantic
                if after?.enabled == true {
                    self.showFlash("Semantic recall ready — \(after?.tier ?? "on").", tone: .success)
                } else {
                    self.showFlash("Needs a one-time install — run: lnk semantic \(LinkCLI.workspace) --setup", tone: .info)
                }
                self.refreshHealth()
            }
        }
    }

    /// Bring link-mcp in the workspace venv to Link's version by running the
    /// exact upgrade command verify-mcp emits, then confirm it actually took.
    func upgradeMCP() {
        guard let command = mcp?.nextActions?.first?.command, !command.isEmpty else {
            repairRuntime()  // fallback: refresh the workspace runtime copy
            return
        }
        busy = true
        showFlash("Updating link-mcp…", tone: .info)
        Task.detached(priority: .userInitiated) {
            _ = try? LinkCLI.runRaw(command)
            let after = try? LinkCLI.runJSON(MCPVerify.self, ["verify-mcp", LinkCLI.workspace, "--json"])
            await MainActor.run {
                self.busy = false
                self.mcp = after ?? self.mcp
                if after?.ready == true {
                    self.showFlash("MCP updated to Link \(after?.expectedVersion ?? "").", tone: .success)
                } else {
                    self.showFlash("Couldn't auto-update — run: \(command.joined(separator: " "))", tone: .info)
                }
                self.refreshHealth()
            }
        }
    }

    /// Wire Claude Code's session hooks (capture on session end, brief on
    /// session start) — the automatic loop, one click — then confirm they
    /// actually landed in the settings file.
    func wireClaudeHooks() {
        busy = true
        showFlash("Wiring Claude Code hooks…", tone: .info)
        Task.detached(priority: .userInitiated) {
            _ = try? LinkCLI.run(["connect", "claude-code", LinkCLI.workspace, "--hooks", "--write"])
            let wired = Self.claudeHooksAreWired()
            await MainActor.run {
                self.busy = false
                self.claudeHooksWired = wired
                self.showFlash(wired
                    ? "Hooks wired — new sessions capture automatically."
                    : "Couldn't wire hooks — check Claude Code settings.",
                    tone: wired ? .success : .info)
                self.refreshHealth()
            }
        }
    }

    func openInstallDocs() {
        NSWorkspace.shared.open(URL(string: "https://github.com/gowtham0992/link#quick-start")!)
    }

    func revealMemory(named name: String) {
        let path = (LinkCLI.workspace as NSString)
            .appendingPathComponent("wiki/memories/\(name).md")
        NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
    }

    func revealCapture(_ capture: CaptureItem) {
        let path = (LinkCLI.workspace as NSString).appendingPathComponent(capture.path)
        NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
    }

    func setLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            launchAtLogin = SMAppService.mainApp.status == .enabled
        } catch {
            launchAtLogin = SMAppService.mainApp.status == .enabled
            showFlash("Login item needs the bundled app (Scripts/bundle.sh).", tone: .info)
        }
    }

    /// Put text on the clipboard — for pasting a memory into a prompt.
    func copyText(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        showFlash("Copied.", tone: .success)
    }

    func clearSearch() {
        recallResults = []
        searchedQuery = nil
        abstention = nil
    }

    func openWorkspace() {
        NSWorkspace.shared.open(URL(fileURLWithPath: LinkCLI.workspace))
    }

    /// Open the full Memory Dashboard in the browser, starting the local
    /// viewer first if it is not already running (127.0.0.1 only — the
    /// viewer refuses to bind anywhere else by design).
    func openDashboard(path: String = "/memory") {
        busy = true
        Task.detached(priority: .userInitiated) {
            let dashboard = URL(string: "http://127.0.0.1:3000\(path)")!
            if await Self.viewerResponds() {
                await MainActor.run {
                    NSWorkspace.shared.open(dashboard)
                    self.busy = false
                }
                return
            }
            LinkCLI.launchDetached(["serve", LinkCLI.workspace, "--port", "3000"])
            for _ in 0..<20 where !(await Self.viewerResponds()) {
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
            await MainActor.run {
                NSWorkspace.shared.open(dashboard)
                self.showFlash("Viewer started at 127.0.0.1:3000", tone: .success)
                self.busy = false
            }
        }
    }

    /// Show a transient status line; fades on its own.
    private func showFlash(_ message: String, tone: FlashTone) {
        flashGeneration += 1
        let generation = flashGeneration
        flash = message
        flashTone = tone
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            if self.flashGeneration == generation {
                withAnimation(.easeOut(duration: 0.4)) { self.flash = nil }
            }
        }
    }

    private static func viewerResponds() async -> Bool {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:3000/memory")!)
        request.timeoutInterval = 0.5
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return false }
            // Some other dev server may own :3000 — only treat it as ours
            // when the page is recognizably the Link viewer.
            let body = String(data: data.prefix(4096), encoding: .utf8) ?? ""
            return body.contains("Link")
        } catch {
            return false
        }
    }

    private func act(_ args: [String]) {
        busy = true
        Task.detached(priority: .userInitiated) {
            do {
                _ = try LinkCLI.run(args)
                await MainActor.run { self.refresh() }
            } catch {
                await MainActor.run {
                    self.lastError = String(describing: error)
                    self.busy = false
                }
            }
        }
    }
}

/// Minimal kqueue-backed directory watcher: fires on writes, adds, deletes.
final class DirectoryWatcher {
    private let source: DispatchSourceFileSystemObject

    init?(path: String, onChange: @escaping () -> Void) {
        let descriptor = open(path, O_EVTONLY)
        guard descriptor >= 0 else { return nil }
        source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: descriptor,
            eventMask: [.write, .extend, .rename, .delete],
            queue: DispatchQueue.global(qos: .utility)
        )
        source.setEventHandler(handler: onChange)
        source.setCancelHandler { close(descriptor) }
        source.resume()
    }

    deinit {
        source.cancel()
    }
}
