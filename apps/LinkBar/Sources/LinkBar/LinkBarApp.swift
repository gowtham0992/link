import SwiftUI

/// LinkBar — the review gate in your menu bar.
///
/// Link's promise is that nothing becomes durable memory without your
/// approval; LinkBar makes approving ambient instead of a chore. The icon
/// is Link's memory-graph mark, the badge is everything pending your
/// judgment (memories to review + captures to accept), the popover is the
/// inbox. The `lnk` CLI's --json output is the entire backend.
@main
struct LinkBarApp: App {
    @StateObject private var store = LinkStore()

    var body: some Scene {
        MenuBarExtra {
            PopoverView()
                .environmentObject(store)
                .onAppear {
                    store.start()
                    PaletteController.shared.install(store: store)
                    NotificationManager.shared.install(store: store)
                }
        } label: {
            HStack(spacing: 3) {
                if let icon = Self.menuIcon {
                    Image(nsImage: icon)
                } else {
                    Image(systemName: "circle.hexagongrid")
                }
                if store.pendingCount > 0 {
                    Text("\(store.pendingCount)")
                        .font(.system(size: 11, weight: .semibold))
                } else if !store.activeSessions.isEmpty {
                    // Agents are writing transcripts right now and nothing
                    // needs you: a quiet green dot says memory is being made.
                    Circle()
                        .fill(Color(red: 0.30, green: 0.72, blue: 0.42))
                        .frame(width: 5, height: 5)
                } else if store.anyUnhealthy {
                    // No pending reviews, but a Link surface needs attention
                    // (stale runtime, MCP drift, hooks not wired): a subtle
                    // amber dot invites a look at the Status tab.
                    Circle()
                        .fill(Color(red: 0.90, green: 0.62, blue: 0.20))
                        .frame(width: 6, height: 6)
                }
            }
            .onAppear { Self.snapshotIfRequested(store: store); Self.notifyTestIfRequested() }
        }
        .menuBarExtraStyle(.window)
    }

    /// Development aid: LINKBAR_SNAPSHOT=/path.png renders the popover to a
    /// PNG (after one refresh) and exits — screenshot verification without
    /// menubar clicks or screen-recording permission.
    /// LINKBAR_NOTIFY_TEST=1 asks macOS for notification authorization,
    /// prints the verdict, and exits — the ad-hoc-signing viability check.
    @MainActor
    static func notifyTestIfRequested() {
        let marker = "/tmp/linkbar-notify-probe"
        let byEnv = ProcessInfo.processInfo.environment["LINKBAR_NOTIFY_TEST"] != nil
        let byFile = FileManager.default.fileExists(atPath: marker)
        guard byEnv || byFile else { return }
        NotificationManager.shared.probeAuthorization { result in
            let line = "LINKBAR_NOTIFY: " + result + "\n"
            try? line.write(toFile: "/tmp/linkbar-notify-result.txt", atomically: true, encoding: .utf8)
            FileHandle.standardError.write(line.data(using: .utf8)!)
            try? FileManager.default.removeItem(atPath: marker)
            NSApplication.shared.terminate(nil)
        }
    }

    @MainActor
    static func snapshotIfRequested(store: LinkStore) {
        guard let path = ProcessInfo.processInfo.environment["LINKBAR_SNAPSHOT"] else { return }
        if let appearance = ProcessInfo.processInfo.environment["LINKBAR_APPEARANCE"] {
            NSApplication.shared.appearance = NSAppearance(
                named: appearance == "light" ? .aqua : .darkAqua
            )
        }
        store.start()
        let palette = ProcessInfo.processInfo.environment["LINKBAR_PALETTE"] != nil
        Task { @MainActor in
            // Real AppKit backing so SF Symbols and text fields render.
            let host = NSHostingView(
                rootView: AnyView(palette
                    ? AnyView(PaletteView(dismiss: {}).environmentObject(store)
                        .frame(width: 560).padding(24).background(Color.black.opacity(0.35)))
                    : AnyView(PopoverView().environmentObject(store)
                        .background(Color(nsColor: .windowBackgroundColor))))
            )
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 380, height: 10),
                styleMask: [.borderless], backing: .buffered, defer: false
            )
            window.contentView = host
            window.setContentSize(host.fittingSize)
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            window.setContentSize(host.fittingSize)
            host.layoutSubtreeIfNeeded()
            if let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
                host.cacheDisplay(in: host.bounds, to: rep)
                if let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: path))
                }
            }
            NSApplication.shared.terminate(nil)
        }
    }

    /// The Link mark as a template image so it adapts to menu bar appearance.
    private static let menuIcon: NSImage? = {
        guard let url = Bundle.module.url(forResource: "MenuIcon", withExtension: "png"),
              let image = NSImage(contentsOf: url)
        else { return nil }
        image.isTemplate = true
        image.size = NSSize(width: 18, height: 18)
        return image
    }()
}
