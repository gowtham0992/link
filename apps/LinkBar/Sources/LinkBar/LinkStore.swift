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
    @Published var runtimeWarning: String?
    @Published var launchAtLogin: Bool = SMAppService.mainApp.status == .enabled

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
            let captures = try? LinkCLI.runJSON(CaptureInbox.self, ["capture-inbox", workspace, "--json"])
            let log = try? LinkCLI.runJSON(MemoryLog.self, ["memory-log", workspace, "--json", "--limit", "200"])
            let status = try? LinkCLI.runJSON(StatusPayload.self, ["status", workspace, "--json"])
            await MainActor.run {
                if inbox == nil && captures == nil {
                    self.lastError = "Could not reach lnk — is Link installed? (brew install gowtham0992/link/link)"
                } else {
                    self.lastError = nil
                }
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
            }
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

    func deleteCapture(_ capture: CaptureItem) {
        act(["delete-capture", capture.path, LinkCLI.workspace, "--confirm"])
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
    func openDashboard() {
        busy = true
        Task.detached(priority: .userInitiated) {
            let dashboard = URL(string: "http://127.0.0.1:3000/memory")!
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
