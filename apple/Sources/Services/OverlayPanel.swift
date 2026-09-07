#if os(macOS)
import AppKit
import SwiftUI

/// The small floating panel, built by hand rather than as a SwiftUI `Window`.
///
/// A SwiftUI window scene insists on drawing its own background, which showed
/// up as a second rounded rectangle around the panel — a box around the box.
/// The APIs that would remove it (`.windowStyle(.plain)`, `.containerBackground`)
/// need a newer macOS than this app targets. An `NSPanel` has no such opinion:
/// borderless, transparent, and the view draws the only shape there is.
@MainActor
final class OverlayPanelController {
    private var panel: NSPanel?
    private var frameObserver: Any?
    private static let positionKey = "overlayPanelOrigin"
    private static let size = NSSize(width: 232, height: 62)

    func show(model: AppModel) {
        let panel = panel ?? make(model: model)
        self.panel = panel
        // `orderFrontRegardless` rather than `makeKeyAndOrderFront`: the user
        // hid the app to work somewhere else, and stealing focus would undo
        // exactly what they asked for.
        panel.orderFrontRegardless()
    }

    func hide() {
        panel?.orderOut(nil)
    }

    private func make(model: AppModel) -> NSPanel {
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: Self.size),
            // .nonactivatingPanel keeps the app in the background when the
            // panel is clicked, which is what lets it be used mid-hide.
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.canHide = false                  // survives ⌘H — the whole point
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.animationBehavior = .utilityWindow

        let host = NSHostingView(rootView: OverlayView().environmentObject(model))
        host.frame = NSRect(origin: .zero, size: Self.size)
        panel.contentView = host

        panel.setFrameOrigin(storedOrigin(for: panel))
        // Remember where the user put it; the default only applies until they
        // move it once.
        frameObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.didMoveNotification, object: panel, queue: .main) { note in
                guard let moved = note.object as? NSWindow else { return }
                let origin = moved.frame.origin
                UserDefaults.standard.set([origin.x, origin.y], forKey: Self.positionKey)
            }
        return panel
    }

    /// Centred above the Dock by default — where a push-to-talk indicator
    /// belongs, and where the eye already goes.
    private func storedOrigin(for panel: NSPanel) -> NSPoint {
        if let stored = UserDefaults.standard.array(forKey: Self.positionKey) as? [Double],
           stored.count == 2 {
            let point = NSPoint(x: stored[0], y: stored[1])
            // A screen that has since been unplugged must not strand it.
            if NSScreen.screens.contains(where: { $0.visibleFrame.insetBy(dx: -40, dy: -40).contains(point) }) {
                return point
            }
        }
        let visible = (panel.screen ?? NSScreen.main)?.visibleFrame ?? .zero
        return NSPoint(x: visible.midX - Self.size.width / 2, y: visible.minY + 14)
    }
}
#endif
