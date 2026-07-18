import AppKit
import Carbon.HIToolbox
import SwiftUI

/// The Memory Palette: a global hotkey (⌥⌘M) that opens a floating panel
/// over any app — type to recall memory, prefix with "+" to remember.
/// Carbon's RegisterEventHotKey needs no permissions (unlike global event
/// monitors, which require Input Monitoring), so this works in an
/// unsigned/ad-hoc build.
final class PaletteController {
    static let shared = PaletteController()

    private var panel: NSPanel?
    private var hotKeyRef: EventHotKeyRef?
    private weak var store: LinkStore?

    func install(store: LinkStore) {
        self.store = store
        registerHotKey()
    }

    // MARK: hotkey (⌥⌘M)

    private func registerHotKey() {
        let signature = OSType(0x4C4E4B42) // "LNKB"
        var hotKeyID = EventHotKeyID(signature: signature, id: 1)
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                      eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            DispatchQueue.main.async { PaletteController.shared.toggle() }
            return noErr
        }, 1, &eventType, nil, nil)
        RegisterEventHotKey(UInt32(kVK_ANSI_M),
                            UInt32(optionKey | cmdKey),
                            hotKeyID,
                            GetApplicationEventTarget(),
                            0,
                            &hotKeyRef)
    }

    // MARK: panel lifecycle

    func toggle() {
        if let panel, panel.isVisible {
            hide()
        } else {
            show()
        }
    }

    func show() {
        guard let store else { return }
        let panel = self.panel ?? makePanel(store: store)
        self.panel = panel
        // Center on the screen with the mouse (multi-display friendly).
        if let screen = NSScreen.screens.first(where: { NSMouseInRect(NSEvent.mouseLocation, $0.frame, false) }) ?? NSScreen.main {
            let frame = screen.frame
            let size = panel.frame.size
            panel.setFrameOrigin(NSPoint(
                x: frame.midX - size.width / 2,
                y: frame.midY - size.height / 2 + frame.height * 0.12
            ))
        }
        panel.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func hide() {
        panel?.orderOut(nil)
    }

    private func makePanel(store: LinkStore) -> NSPanel {
        let panel = KeyablePanel(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 100),
            styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isMovableByWindowBackground = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true

        let host = NSHostingView(rootView: PaletteView(dismiss: { [weak self] in self?.hide() })
            .environmentObject(store))
        panel.contentView = host
        return panel
    }
}

/// NSPanel refuses key status by default with .nonactivatingPanel; the
/// palette needs it so the search field can accept typing immediately.
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override func cancelOperation(_ sender: Any?) { orderOut(nil) } // Esc closes
}
