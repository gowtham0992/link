import SwiftUI

struct PopoverView: View {
    @EnvironmentObject var store: LinkStore
    @State private var query = ""
    @State private var showSettings = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if let warning = store.runtimeWarning {
                runtimeBanner(warning)
            }
            recallField
            if store.searchedQuery != nil || !store.recallResults.isEmpty {
                recallSection
                Divider()
            }
            inboxSection
            if let captures = store.captures, !captures.captures.isEmpty {
                Divider()
                capturesSection(captures)
            }
            if !store.activity.isEmpty {
                Divider()
                activitySection
            }
            footer
        }
        .padding(12)
        .frame(width: 380)
        .sheet(isPresented: $showSettings) {
            SettingsSheet()
                .environmentObject(store)
        }
    }

    private var header: some View {
        HStack {
            Text("Link").font(.headline)
            Spacer()
            if store.busy { ProgressView().controlSize(.small) }
            Button {
                store.rememberClipboard()
            } label: { Image(systemName: "doc.on.clipboard") }
                .buttonStyle(.borderless)
                .help("Remember clipboard — saved as pending review")
            Button {
                store.openDashboard()
            } label: { Image(systemName: "gauge.with.needle") }
                .buttonStyle(.borderless)
                .help("Open the Memory Dashboard (starts the local viewer if needed)")
            Button {
                store.openWorkspace()
            } label: { Image(systemName: "folder") }
                .buttonStyle(.borderless)
                .help("Open the workspace in Finder")
            Button {
                store.refresh()
            } label: { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.borderless)
                .keyboardShortcut("r", modifiers: .command)
                .help("Refresh (⌘R)")
            Button {
                showSettings = true
            } label: { Image(systemName: "gearshape") }
                .buttonStyle(.borderless)
                .help("Settings")
        }
    }

    /// The post-upgrade drift warning, with its one-click repair.
    private func runtimeBanner(_ warning: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.yellow)
            Text(warning)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button("Fix") { store.repairRuntime() }
                .controlSize(.small)
                .help("Refresh the workspace runtime (lnk init)")
        }
        .padding(8)
        .background(.yellow.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private var recallField: some View {
        HStack(spacing: 6) {
            TextField("Ask your memory — or type something to keep…", text: $query)
                .textFieldStyle(.roundedBorder)
                .onSubmit { store.recall(query) }
            Button {
                store.rememberText(query)
                query = ""
            } label: { Image(systemName: "plus.circle") }
                .buttonStyle(.borderless)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty)
                .help("Remember this text (⌘↩) — saved as pending review")
        }
    }

    private var recallSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            if store.recallResults.isEmpty, store.abstention?.recommended != true,
               let searched = store.searchedQuery {
                Label(
                    "No matches for \"\(searched)\" — try different words.",
                    systemImage: "magnifyingglass"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            if let abstention = store.abstention, abstention.recommended {
                Label(
                    "Nothing reliable on this — the honest answer is \"don't know\".",
                    systemImage: "questionmark.circle"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            ForEach(store.recallResults.prefix(4)) { memory in
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(memory.title).font(.callout).lineLimit(1)
                        Spacer()
                        if let confidence = memory.confidence {
                            Text(confidence)
                                .font(.caption2)
                                .padding(.horizontal, 5)
                                .background(confidenceColor(confidence).opacity(0.2))
                                .clipShape(Capsule())
                        }
                    }
                    if let tldr = memory.tldr {
                        Text(tldr).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                .contentShape(Rectangle())
                .contextMenu {
                    Button("Reveal in Finder") { store.revealMemory(named: memory.name) }
                }
                .onTapGesture(count: 2) { store.revealMemory(named: memory.name) }
                .help("Double-click or right-click to open the memory file")
            }
        }
    }

    private var inboxSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            let items = store.inbox?.items ?? []
            HStack {
                Text("Review inbox").font(.subheadline).bold()
                Spacer()
                Text("\(store.inbox?.reviewCount ?? 0)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if items.isEmpty {
                Label("Nothing waiting — your memory is fully reviewed.", systemImage: "checkmark.seal")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(items.prefix(5)) { item in
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.title).font(.callout).lineLimit(1)
                        HStack(spacing: 6) {
                            Text(item.memoryType).font(.caption2).foregroundStyle(.secondary)
                            if let tldr = item.tldr {
                                Text(tldr).font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                            }
                        }
                    }
                    .contentShape(Rectangle())
                    .contextMenu {
                        Button("Reveal in Finder") { store.revealMemory(named: item.name) }
                    }
                    Spacer()
                    Button("✓") { store.markReviewed(item) }
                        .buttonStyle(.borderedProminent)
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

    private func capturesSection(_ captures: CaptureInbox) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Session captures").font(.subheadline).bold()
                Spacer()
                Text("\(captures.count)").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(captures.captures.prefix(3)) { capture in
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(capture.displayTitle).font(.callout).lineLimit(1)
                        HStack(spacing: 6) {
                            if let stamp = capture.capturedAt {
                                Text(stamp).font(.caption2).foregroundStyle(.secondary)
                            }
                            if let project = capture.project, !project.isEmpty {
                                Text(project).font(.caption2).foregroundStyle(.tertiary)
                            }
                        }
                        if let first = capture.proposals?.first, let memory = first.memory {
                            Text("Will save: \(memory)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        } else if let snippet = capture.snippet, !snippet.isEmpty {
                            Text(snippet)
                                .font(.caption)
                                .foregroundStyle(.tertiary)
                                .lineLimit(2)
                        }
                    }
                    .contentShape(Rectangle())
                    .contextMenu {
                        Button("Reveal in Finder") { store.revealCapture(capture) }
                    }
                    Spacer()
                    Button("Accept") { store.acceptCapture(capture) }
                        .buttonStyle(.borderedProminent)
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

    private var activitySection: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Recent activity").font(.subheadline).bold()
            ForEach(store.activity.prefix(3)) { entry in
                HStack(spacing: 6) {
                    Text(entry.operation)
                        .font(.caption2)
                        .padding(.horizontal, 5)
                        .background(Color.secondary.opacity(0.15))
                        .clipShape(Capsule())
                    Text(entry.description ?? "")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let flash = store.flash {
                Text(flash)
                    .font(.caption2)
                    .foregroundStyle(store.flashTone == .success ? Color.green : Color.secondary)
                    .lineLimit(1)
                    .transition(.opacity)
            }
            if let error = store.lastError {
                Text(error).font(.caption2).foregroundStyle(.red).lineLimit(2)
            }
            Divider()
            HStack {
                Text(LinkCLI.workspace)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                    .truncationMode(.head)
                Spacer()
                Text("LinkBar 0.4" + (store.linkVersion.isEmpty ? "" : " · Link \(store.linkVersion)"))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Button("Quit") { NSApplication.shared.terminate(nil) }
                    .buttonStyle(.borderless)
                    .font(.caption)
                    .keyboardShortcut("q", modifiers: .command)
            }
        }
    }

    private func confidenceColor(_ value: String) -> Color {
        switch value {
        case "strong": return .green
        case "moderate": return .orange
        default: return .gray
        }
    }
}

struct SettingsSheet: View {
    @EnvironmentObject var store: LinkStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("LinkBar Settings").font(.headline)

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
                Text("Updates").font(.subheadline)
                Text("LinkBar refreshes the moment your workspace changes — session hooks, agents, and edits all show up live.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack {
                if !store.linkVersion.isEmpty {
                    Text("Link \(store.linkVersion)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
                Spacer()
                Button("Done") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(16)
        .frame(width: 340)
    }
}
