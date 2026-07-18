import SwiftUI

struct PopoverView: View {
    enum Tab { case inbox, status, settings }

    @EnvironmentObject var store: LinkStore
    @State private var query = ""
    // Snapshot aid: LINKBAR_TAB=status opens straight to the Status tab.
    @State private var tab: Tab =
        ProcessInfo.processInfo.environment["LINKBAR_TAB"] == "status" ? .status : .inbox

    private var isFullyIdle: Bool {
        (store.inbox?.items.isEmpty ?? true)
            && (store.captures?.captures.isEmpty ?? true)
            && store.recallResults.isEmpty
            && store.searchedQuery == nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
                .padding(.horizontal, LinkBrand.pad)
                .padding(.top, LinkBrand.pad)
            tabBar
                .padding(.horizontal, LinkBrand.pad)
                .padding(.top, 10)
            Divider().opacity(0.35).padding(.top, 8)

            Group {
                switch tab {
                case .inbox: inboxTab
                case .status: statusTab
                case .settings:
                    SettingsPane(done: { tab = .inbox })
                        .environmentObject(store)
                }
            }
            .animation(.easeOut(duration: 0.18), value: store.pendingCount)

            footer
                .padding(.horizontal, LinkBrand.pad)
                .padding(.bottom, LinkBrand.pad)
        }
        .frame(width: 380)
    }

    // MARK: tab bar

    private var tabBar: some View {
        HStack(spacing: 4) {
            tabButton("Inbox", .inbox, badge: store.pendingCount)
            tabButton("Status", .status, alert: store.anyUnhealthy)
            tabButton("Settings", .settings)
            Spacer()
        }
    }

    private func tabButton(_ label: String, _ value: Tab, badge: Int = 0, alert: Bool = false) -> some View {
        let active = tab == value
        return Button {
            tab = value
            if value == .status { store.refreshHealth() }
        } label: {
            HStack(spacing: 4) {
                Text(label)
                    .font(.system(size: 12, weight: active ? .semibold : .regular))
                if badge > 0 {
                    Text("\(badge)")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .background(LinkBrand.rust, in: Capsule())
                } else if alert {
                    Circle().fill(Color(red: 0.90, green: 0.62, blue: 0.20)).frame(width: 6, height: 6)
                }
            }
            .foregroundStyle(active ? AnyShapeStyle(LinkBrand.rust) : AnyShapeStyle(.secondary))
            .padding(.horizontal, 9).padding(.vertical, 4)
            .background(active ? AnyShapeStyle(LinkBrand.rust.opacity(0.12)) : AnyShapeStyle(.clear),
                        in: RoundedRectangle(cornerRadius: 7))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: inbox tab (the original memory view)

    private var inboxTab: some View {
        VStack(alignment: .leading, spacing: LinkBrand.betweenSections) {
            if !store.activeSessions.isEmpty {
                pulseRow
            }
            if let warning = store.runtimeWarning {
                runtimeBanner(warning)
            }
            recallField
            if store.searchedQuery != nil || !store.recallResults.isEmpty {
                recallSection
            }
            if isFullyIdle {
                idleState
            } else {
                inboxSection
                if let captures = store.captures, !captures.captures.isEmpty {
                    capturesSection(captures)
                }
            }
            if !store.activity.isEmpty && !isFullyIdle {
                activitySection
            }
        }
        .padding(LinkBrand.pad)
    }

    /// Live agent pulse: which sessions are writing transcripts right now,
    /// and when memory last changed — the ambient "memory is being made" row.
    private var pulseRow: some View {
        HStack(spacing: 8) {
            PulseDot()
            Text(pulseText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer()
            if let last = store.activity.first?.date {
                Text("memory · \(last.relativeLabel)")
                    .font(.system(size: 10))
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(Color.green.opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
    }

    private var pulseText: String {
        let sessions = store.activeSessions
        let names = sessions.prefix(3).map(\.project).joined(separator: ", ")
        let count = sessions.count == 1 ? "1 agent" : "\(sessions.count) agents"
        return "\(count) active · \(names)"
    }

    // MARK: status tab (health of every Link surface)

    private var statusTab: some View {
        VStack(alignment: .leading, spacing: LinkBrand.inGroup) {
            HStack {
                SectionHeader(title: "Link status")
                Spacer()
                Text(store.anyUnhealthy ? "Needs attention" : "All systems go")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(store.anyUnhealthy
                        ? Color(red: 0.90, green: 0.62, blue: 0.20) : .green)
            }
            ForEach(store.surfaces()) { surface in
                StatusRow(surface: surface)
            }
        }
        .padding(LinkBrand.pad)
    }

    // MARK: header

    private var header: some View {
        HStack(spacing: 2) {
            Wordmark()
            Spacer()
            if store.busy {
                ProgressView().controlSize(.small).padding(.trailing, 4)
            }
            toolbarButton("doc.on.clipboard", help: "Remember clipboard — saved as pending review") {
                store.rememberClipboard()
            }
            toolbarButton("gauge.with.needle", help: "Open the Memory Dashboard") {
                store.openDashboard()
            }
            toolbarButton("folder", help: "Open the workspace in Finder") {
                store.openWorkspace()
            }
            toolbarButton("arrow.clockwise", help: "Refresh (⌘R)") {
                store.refresh()
                store.refreshHealth()
            }
            .keyboardShortcut("r", modifiers: .command)
        }
    }

    private func toolbarButton(_ symbol: String, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 12, weight: .medium))
                .frame(width: 24, height: 22)
                .contentShape(Rectangle())
        }
        .buttonStyle(.borderless)
        .foregroundStyle(.secondary)
        .help(help)
    }

    /// The post-upgrade drift warning, with its one-click repair.
    private func runtimeBanner(_ warning: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.yellow)
                .font(.caption)
            Text(warning)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
            Button("Fix") { store.repairRuntime() }
                .controlSize(.small)
                .tint(LinkBrand.rust)
                .help("Refresh the workspace runtime (lnk init)")
        }
        .padding(10)
        .background(.yellow.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
    }

    // MARK: ask / remember

    private var recallField: some View {
        HStack(spacing: 6) {
            HStack(spacing: 5) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
                TextField("Ask your memory — or type something to keep…", text: $query)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12.5))
                    .onSubmit { store.recall(query) }
                if !query.isEmpty || store.searchedQuery != nil {
                    Button {
                        query = ""
                        store.clearSearch()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                    }
                    .buttonStyle(.borderless)
                    .help("Clear the search")
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 7))
            Button {
                store.rememberText(query)
                query = ""
            } label: {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 17))
                    .foregroundStyle(
                        query.trimmingCharacters(in: .whitespaces).isEmpty
                            ? AnyShapeStyle(.quaternary) : AnyShapeStyle(LinkBrand.rust)
                    )
            }
            .buttonStyle(.borderless)
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty)
            .help("Remember this text (⌘↩) — saved as pending review")
        }
    }

    private var recallSection: some View {
        VStack(alignment: .leading, spacing: LinkBrand.inGroup) {
            SectionHeader(title: "Recall", count: store.recallResults.isEmpty ? nil : store.recallResults.count)
            if store.recallResults.isEmpty, store.abstention?.recommended != true,
               let searched = store.searchedQuery {
                Label("No matches for \u{201C}\(searched)\u{201D} — try different words.", systemImage: "questionmark.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
            }
            if let abstention = store.abstention, abstention.recommended {
                Label("Nothing reliable on this — the honest answer is \u{201C}don't know\u{201D}.", systemImage: "hand.raised")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
            }
            ForEach(store.recallResults.prefix(4)) { memory in
                HoverRow {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(memory.title)
                                .font(.system(size: 12.5, weight: .medium))
                                .lineLimit(1)
                            Spacer()
                            if let confidence = memory.confidence {
                                confidenceChip(confidence)
                            }
                        }
                        if let tldr = memory.tldr {
                            Text(tldr).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                    .contextMenu {
                        Button("Copy text") { store.copyText(memory.tldr ?? memory.title) }
                        Button("Reveal in Finder") { store.revealMemory(named: memory.name) }
                    }
                    .onTapGesture(count: 2) { store.revealMemory(named: memory.name) }
                }
                .help("Double-click to open · right-click to copy")
            }
        }
    }

    private func confidenceChip(_ value: String) -> some View {
        Text(value)
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(confidenceColor(value))
            .padding(.horizontal, 6)
            .padding(.vertical, 1.5)
            .background(confidenceColor(value).opacity(0.13))
            .clipShape(Capsule())
    }

    // MARK: review inbox

    private var inboxSection: some View {
        VStack(alignment: .leading, spacing: LinkBrand.inGroup) {
            let items = store.inbox?.items ?? []
            SectionHeader(
                title: "Review inbox",
                count: store.inbox?.reviewCount ?? 0,
                highlight: (store.inbox?.reviewCount ?? 0) > 0
            )
            if items.isEmpty {
                Label("Nothing waiting — your memory is fully reviewed.", systemImage: "checkmark.seal")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
            }
            ForEach(items.prefix(5)) { item in
                HoverRow {
                    HStack(alignment: .center, spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title)
                                .font(.system(size: 12.5, weight: .medium))
                                .lineLimit(1)
                            HStack(spacing: 6) {
                                Text(item.memoryType)
                                    .font(.system(size: 10.5))
                                    .foregroundStyle(LinkBrand.rust)
                                if let tldr = item.tldr {
                                    Text(tldr).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                                }
                            }
                        }
                        .contentShape(Rectangle())
                        .contextMenu {
                            Button("Reveal in Finder") { store.revealMemory(named: item.name) }
                        }
                        Spacer(minLength: 6)
                        Button {
                            store.markReviewed(item)
                        } label: { Image(systemName: "checkmark") }
                            .buttonStyle(.borderedProminent)
                            .tint(LinkBrand.rust)
                            .controlSize(.small)
                            .help("Mark reviewed — confirm this memory is accurate")
                        Button {
                            store.archive(item)
                        } label: { Image(systemName: "archivebox") }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .help("Archive — keep it out of recall, never deleted")
                    }
                }
            }
        }
    }

    // MARK: captures

    private func capturesSection(_ captures: CaptureInbox) -> some View {
        VStack(alignment: .leading, spacing: LinkBrand.inGroup) {
            SectionHeader(title: "Session captures", count: captures.count, highlight: captures.count > 0)
            ForEach(captures.captures.prefix(3)) { capture in
                HoverRow {
                    HStack(alignment: .center, spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Text(capture.displayTitle)
                                    .font(.system(size: 12.5, weight: .medium))
                                    .lineLimit(1)
                                if let stamp = capture.capturedAt {
                                    Text(stamp).font(.system(size: 10.5)).foregroundStyle(.tertiary)
                                }
                            }
                            if let first = capture.proposals?.first, let memory = first.memory {
                                (Text("Will save: ").foregroundStyle(.tertiary)
                                    + Text(memory).foregroundStyle(.secondary))
                                    .font(.caption)
                                    .lineLimit(2)
                            } else if let snippet = capture.snippet, !snippet.isEmpty {
                                Text(snippet)
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                                    .lineLimit(2)
                            }
                            if let trail = capture.decisionTrail, !trail.isEmpty {
                                DisclosureGroup {
                                    VStack(alignment: .leading, spacing: 2) {
                                        ForEach(Array(trail.enumerated()), id: \.offset) { _, step in
                                            Text("• \(step)")
                                                .font(.caption2)
                                                .foregroundStyle(.tertiary)
                                                .fixedSize(horizontal: false, vertical: true)
                                        }
                                    }
                                    .padding(.top, 2)
                                } label: {
                                    Text("How Link read this session")
                                        .font(.caption2)
                                        .foregroundStyle(LinkBrand.rust)
                                }
                            }
                        }
                        .contentShape(Rectangle())
                        .contextMenu {
                            Button("Reveal in Finder") { store.revealCapture(capture) }
                        }
                        Spacer(minLength: 6)
                        if let proposals = capture.proposals, proposals.count > 1 {
                            Menu("Accept") {
                                ForEach(Array(proposals.enumerated()), id: \.offset) { position, proposal in
                                    Button(proposal.title ?? proposal.memory?.prefix(60).description ?? "Proposal \(position + 1)") {
                                        store.acceptCapture(capture, index: position + 1)
                                    }
                                }
                            }
                            .menuStyle(.borderedButton)
                            .controlSize(.small)
                            .frame(width: 76)
                            .help("This session proposed \(proposals.count) memories — pick one to accept")
                        } else {
                            Button("Accept") { store.acceptCapture(capture) }
                                .buttonStyle(.borderedProminent)
                                .tint(LinkBrand.rust)
                                .controlSize(.small)
                                .help("Accept the proposal into reviewed memory")
                        }
                        Button {
                            store.deleteCapture(capture)
                        } label: { Image(systemName: "trash") }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .help("Discard this capture")
                    }
                }
            }
        }
    }

    // MARK: activity, idle, footer

    private var activitySection: some View {
        VStack(alignment: .leading, spacing: LinkBrand.inGroup) {
            SectionHeader(title: "Recent activity")
            VStack(alignment: .leading, spacing: 4) {
                ForEach(store.activity.prefix(3)) { entry in
                    HStack(spacing: 6) {
                        Text(entry.operation)
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 1)
                            .background(.quaternary.opacity(0.6))
                            .clipShape(Capsule())
                        Text(entry.description ?? "")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }
            }
            .padding(.horizontal, 8)
        }
    }

    /// Everything reviewed, nothing captured, nothing searched — show the
    /// workspace at a glance instead of an empty room: counts, the last
    /// fortnight's pulse, and the most recent thing Link did.
    private var idleState: some View {
        VStack(alignment: .leading, spacing: LinkBrand.inGroup) {
            SectionHeader(title: "Your memory")
            HStack(spacing: 0) {
                StatChip(
                    value: "\(store.stats?.activeMemoryCount ?? 0)",
                    label: "active",
                    tint: LinkBrand.rust
                )
                StatChip(value: "\(store.stats?.memoryCount ?? 0)", label: "memories")
                StatChip(value: "\(store.stats?.contentPageCount ?? 0)", label: "wiki pages")
                StatChip(value: "\(store.stats?.needsReviewCount ?? 0)", label: "to review")
            }
            .padding(.vertical, 6)
            HStack(alignment: .center, spacing: 10) {
                Sparkline(values: store.activityPulse())
                VStack(alignment: .leading, spacing: 1) {
                    Text("Last 14 days")
                        .font(.system(size: 9.5, weight: .medium))
                        .foregroundStyle(.tertiary)
                    if let last = store.activity.first {
                        Text("Latest: \(last.operation)\(last.date.map { " · \($0.relativeLabel)" } ?? "")")
                            .font(.system(size: 9.5))
                            .foregroundStyle(.tertiary)
                            .lineLimit(1)
                    }
                }
                Spacer()
                Image(systemName: "checkmark.seal")
                    .font(.system(size: 15, weight: .light))
                    .foregroundStyle(LinkBrand.rust.opacity(0.75))
                    .help("Everything is reviewed")
            }
            .padding(.horizontal, 8)
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let flash = store.flash {
                HStack(spacing: 5) {
                    Circle()
                        .fill(store.flashTone == .success ? Color.green : Color.secondary)
                        .frame(width: 5, height: 5)
                    Text(flash)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(.quaternary.opacity(0.5), in: Capsule())
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            if let error = store.lastError {
                Text(error).font(.caption2).foregroundStyle(.red).lineLimit(2)
            }
            Divider()
            HStack {
                Text(LinkCLI.workspace)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.quaternary)
                    .lineLimit(1)
                    .truncationMode(.head)
                Spacer()
                Text("LinkBar \(LinkBrand.version)" + (store.linkVersion.isEmpty ? "" : " · Link \(store.linkVersion)"))
                    .font(.system(size: 10.5))
                    .foregroundStyle(.tertiary)
                Button("Quit") { NSApplication.shared.terminate(nil) }
                    .buttonStyle(.borderless)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .keyboardShortcut("q", modifiers: .command)
            }
        }
        .animation(.easeOut(duration: 0.2), value: store.flash)
    }

    private func confidenceColor(_ value: String) -> Color {
        switch value {
        case "strong": return .green
        case "moderate": return .orange
        default: return .gray
        }
    }
}

struct SettingsPane: View {
    @EnvironmentObject var store: LinkStore
    let done: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 7) {
                Wordmark()
                Text("Settings")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.secondary)
            }

            Toggle(isOn: Binding(
                get: { store.launchAtLogin },
                set: { store.setLaunchAtLogin($0) }
            )) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Launch at login")
                    Text("Keep the review gate in your menu bar.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .tint(LinkBrand.rust)

            VStack(alignment: .leading, spacing: 2) {
                Text("Workspace").font(.subheadline)
                Text(LinkCLI.workspace)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Text("Set LINK_WORKSPACE to point LinkBar at a different workspace.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text("Live updates").font(.subheadline)
                Text("LinkBar refreshes the moment your workspace changes — session hooks, agents, and edits all show up instantly.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack {
                if !store.linkVersion.isEmpty {
                    Text("LinkBar \(LinkBrand.version) · Link \(store.linkVersion)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                Spacer()
                Button("Done") { done() }
                    .keyboardShortcut(.defaultAction)
                    .tint(LinkBrand.rust)
            }
        }
        .padding(16)
    }
}
