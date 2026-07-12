import SwiftUI

struct PopoverView: View {
    @EnvironmentObject var store: LinkStore
    @State private var query = ""
    @State private var showSettings = false

    private var isFullyIdle: Bool {
        (store.inbox?.items.isEmpty ?? true)
            && (store.captures?.captures.isEmpty ?? true)
            && store.recallResults.isEmpty
            && store.searchedQuery == nil
    }

    var body: some View {
        Group {
            if showSettings {
                SettingsPane(done: { showSettings = false })
                    .environmentObject(store)
            } else {
                mainContent
            }
        }
        .frame(width: 380)
    }

    private var mainContent: some View {
        VStack(alignment: .leading, spacing: LinkBrand.betweenSections) {
            header
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
            footer
        }
        .padding(LinkBrand.pad)
        .animation(.easeOut(duration: 0.18), value: store.pendingCount)
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
            }
            .keyboardShortcut("r", modifiers: .command)
            toolbarButton("gearshape", help: "Settings") {
                showSettings = true
            }
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
                        Button("Reveal in Finder") { store.revealMemory(named: memory.name) }
                    }
                    .onTapGesture(count: 2) { store.revealMemory(named: memory.name) }
                }
                .help("Double-click or right-click to open the memory file")
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
                        Button("Accept") { store.acceptCapture(capture) }
                            .buttonStyle(.borderedProminent)
                            .tint(LinkBrand.rust)
                            .controlSize(.small)
                            .help("Accept the first proposal into reviewed memory")
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

    /// Everything reviewed, nothing captured, nothing searched: say so nicely.
    private var idleState: some View {
        VStack(spacing: 6) {
            Image(systemName: "checkmark.seal")
                .font(.system(size: 22, weight: .light))
                .foregroundStyle(LinkBrand.rust.opacity(0.8))
            Text("All reviewed.")
                .font(.system(size: 12.5, weight: .medium))
            Text("Your agents remember you — say something worth keeping.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 18)
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
                Text("LinkBar 0.5" + (store.linkVersion.isEmpty ? "" : " · Link \(store.linkVersion)"))
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
                    Text("LinkBar 0.5 · Link \(store.linkVersion)")
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
