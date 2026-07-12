import SwiftUI

/// LinkBar's design tokens: native macOS materials carry the structure,
/// Link's rust carries the opinion, one serif wordmark is the signature.
enum LinkBrand {
    /// One source of truth for the app version shown in footer + settings.
    static let version = "0.6"

    /// Rust — Link's accent. Lifted and desaturated slightly in dark mode
    /// so it reads as warm, not muddy, on dark materials.
    static let rust = Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(red: 0.85, green: 0.47, blue: 0.34, alpha: 1)   // #d97856
            : NSColor(red: 0.66, green: 0.29, blue: 0.18, alpha: 1)   // #a8492f
    })

    /// Spacing scale (4/8 rhythm): tight within groups, generous between.
    static let inGroup: CGFloat = 6
    static let betweenSections: CGFloat = 16
    static let pad: CGFloat = 14
}

/// Uppercase tracked section label with an optional trailing count.
struct SectionHeader: View {
    let title: String
    var count: Int?
    var highlight = false

    var body: some View {
        HStack(spacing: 6) {
            Text(title.uppercased())
                .font(.system(size: 10.5, weight: .semibold))
                .tracking(0.7)
                .foregroundStyle(.secondary)
            Spacer()
            if let count, count > 0 {
                Text("\(count)")
                    .font(.system(size: 10.5, weight: .semibold))
                    .foregroundStyle(highlight ? Color.white : Color.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 1.5)
                    .background(highlight ? AnyShapeStyle(LinkBrand.rust) : AnyShapeStyle(.quaternary))
                    .clipShape(Capsule())
            }
        }
    }
}

/// Row container with a soft hover highlight — the popover feels alive.
struct HoverRow<Content: View>: View {
    @State private var hovering = false
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(hovering ? AnyShapeStyle(.quaternary.opacity(0.6)) : AnyShapeStyle(.clear))
            )
            .onHover { hovering = $0 }
            .animation(.easeOut(duration: 0.15), value: hovering)
    }
}

/// The Link wordmark: the one serif moment in the app.
struct Wordmark: View {
    var body: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(LinkBrand.rust)
                .frame(width: 7, height: 7)
            Text("Link")
                .font(.system(size: 15, weight: .semibold, design: .serif))
        }
    }
}


/// Fourteen days of memory activity as tiny bars — the "pulse" of the
/// workspace. Rust bars on quiet quaternary track; today is the last bar.
struct Sparkline: View {
    let values: [Int]

    private var peak: Int { max(values.max() ?? 1, 1) }

    var body: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(value > 0 ? AnyShapeStyle(LinkBrand.rust.opacity(0.55 + 0.45 * Double(value) / Double(peak)))
                                    : AnyShapeStyle(.quaternary.opacity(0.6)))
                    .frame(width: 9, height: value > 0 ? max(6, 26 * CGFloat(value) / CGFloat(peak)) : 3)
            }
        }
        .frame(height: 26, alignment: .bottom)
        .accessibilityLabel("Memory activity, last \(values.count) days")
    }
}

/// Small stat: big number, quiet label underneath.
struct StatChip: View {
    let value: String
    let label: String
    var tint: Color = .primary

    var body: some View {
        VStack(spacing: 1) {
            Text(value)
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(tint)
            Text(label.uppercased())
                .font(.system(size: 8.5, weight: .medium))
                .tracking(0.5)
                .foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity)
    }
}
