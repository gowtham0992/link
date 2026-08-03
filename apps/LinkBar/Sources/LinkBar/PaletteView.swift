import SwiftUI

/// The floating palette content: one field that recalls as you type and
/// remembers when you prefix with "+". Enter copies the top recall result
/// (or saves, in remember mode); Esc closes.
struct PaletteView: View {
    @EnvironmentObject var store: LinkStore
    let dismiss: () -> Void

    @State private var text = ""
    @State private var results: [RecalledMemory] = []
    @State private var abstention: Abstention?
    @State private var confirmation: String?
    @State private var searching = false
    @FocusState private var focused: Bool
    @State private var debounce: DispatchWorkItem?
    /// Monotonic id per recall; a slow response for an old query must never
    /// overwrite the results of a newer one.
    @State private var recallGeneration = 0
    @State private var pendingDismiss: DispatchWorkItem?

    private var isRemember: Bool { text.hasPrefix("+") }
    private var payload: String {
        isRemember ? String(text.dropFirst()).trimmingCharacters(in: .whitespaces)
                   : text.trimmingCharacters(in: .whitespaces)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            field
            if let confirmation {
                confirmationRow(confirmation)
            } else if isRemember {
                rememberHint
            } else if !results.isEmpty {
                resultsList
            } else if abstention?.recommended == true {
                emptyRow("Nothing reliable on this — the honest answer is \u{201C}don't know.\u{201D}", "hand.raised")
            } else if !payload.isEmpty && !searching {
                emptyRow("No memory matches \u{201C}\(payload)\u{201D}.", "questionmark.circle")
            }
        }
        .frame(width: 560)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.white.opacity(0.08)))
        .onAppear { focused = true }
    }

    // MARK: field

    private var field: some View {
        HStack(spacing: 10) {
            Image(systemName: isRemember ? "plus.circle.fill" : "magnifyingglass")
                .font(.system(size: 15))
                .foregroundStyle(isRemember ? AnyShapeStyle(LinkBrand.rust) : AnyShapeStyle(.secondary))
            TextField("Ask your memory…  (start with + to remember)", text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 17))
                .focused($focused)
                .onSubmit(commit)
                .onChange(of: text) { _, _ in
                    // Typing again revokes a scheduled auto-dismiss: the user
                    // has started a new query and the panel must stay open.
                    pendingDismiss?.cancel()
                    pendingDismiss = nil
                    confirmation = nil
                    scheduleRecall()
                }
            if searching {
                ProgressView().controlSize(.small)
            }
            Text(isRemember ? "return to save" : (results.isEmpty ? "" : "return to copy"))
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 16).padding(.vertical, 14)
    }

    // MARK: recall results

    private var resultsList: some View {
        VStack(alignment: .leading, spacing: 0) {
            Divider().opacity(0.3)
            ForEach(Array(results.prefix(5).enumerated()), id: \.element.id) { index, memory in
                Button {
                    store.copyText(memory.tldr ?? memory.title)
                    confirm("Copied to clipboard")
                } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(index == 0 ? "\u{21A9}" : "\u{00B7}")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(index == 0 ? AnyShapeStyle(LinkBrand.rust) : AnyShapeStyle(.tertiary))
                            .frame(width: 12)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(memory.title).font(.system(size: 13, weight: .medium)).lineLimit(1)
                            if let tldr = memory.tldr {
                                Text(tldr).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                        Spacer()
                        if let c = memory.confidence { confidenceChip(c) }
                    }
                    .padding(.horizontal, 16).padding(.vertical, 8)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.bottom, 6)
    }

    private var rememberHint: some View {
        HStack(spacing: 8) {
            Divider().opacity(0)
            Text(payload.isEmpty
                 ? "Type what to remember — saved as pending your review."
                 : "Saves \u{201C}\(payload)\u{201D} for review. Nothing is trusted until you approve it.")
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 16).padding(.bottom, 12)
    }

    private func confirmationRow(_ message: String) -> some View {
        HStack(spacing: 6) {
            Circle().fill(Color.green).frame(width: 5, height: 5)
            Text(message).font(.caption).foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 16).padding(.bottom, 12)
    }

    private func emptyRow(_ message: String, _ icon: String) -> some View {
        Label(message, systemImage: icon)
            .font(.caption).foregroundStyle(.secondary)
            .padding(.horizontal, 16).padding(.bottom, 12)
    }

    private func confidenceChip(_ value: String) -> some View {
        let color: Color = value == "strong" ? .green : (value == "moderate" ? .orange : .gray)
        return Text(value)
            .font(.system(size: 9, weight: .medium))
            .foregroundStyle(color)
            .padding(.horizontal, 5).padding(.vertical, 1)
            .background(color.opacity(0.13), in: Capsule())
    }

    // MARK: actions

    private func scheduleRecall() {
        debounce?.cancel()
        recallGeneration += 1
        guard !isRemember, !payload.isEmpty else { results = []; abstention = nil; searching = false; return }
        searching = true
        let generation = recallGeneration
        let query = payload
        let work = DispatchWorkItem {
            store.paletteRecall(query) { mems, abst in
                guard generation == recallGeneration else { return }  // stale response
                results = mems; abstention = abst; searching = false
            }
        }
        debounce = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
    }

    private func commit() {
        if isRemember {
            guard !payload.isEmpty else { return }
            store.paletteRemember(payload) { result in
                guard let result else {
                    // nil means the CLI call itself failed — saying "a similar
                    // memory exists" here would be a false diagnosis.
                    confirm("Couldn't reach lnk — check the Status tab.", dismissAfter: false)
                    return
                }
                if result.created == true {
                    confirm("Saved — pending your review")
                } else if result.secret == true {
                    confirm("Not saved — looks like a secret. Use a password manager.")
                } else {
                    confirm("Not saved — a similar or conflicting memory exists.")
                }
            }
        } else if let top = results.first {
            store.copyText(top.tldr ?? top.title)
            confirm("Copied to clipboard")
        }
    }

    /// Show a confirmation, then auto-dismiss the panel shortly after —
    /// unless the user starts typing again first (onChange cancels it).
    private func confirm(_ message: String, dismissAfter: Bool = true) {
        confirmation = message
        pendingDismiss?.cancel()
        guard dismissAfter else { return }
        let work = DispatchWorkItem {
            text = ""; results = []; confirmation = nil
            dismiss()
        }
        pendingDismiss = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.1, execute: work)
    }
}
