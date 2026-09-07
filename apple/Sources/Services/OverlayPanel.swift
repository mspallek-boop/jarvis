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
/// A borderless panel that can still be clicked.
///
/// `canBecomeKey` is false by default for a borderless window, and a window that
/// cannot become key is never sent mouse events — which is why clicking the pill
/// did nothing at all, whatever the click detection was doing. Verified rather
/// than assumed: the same style mask reports false without this override and
/// true with it.
///
/// `.nonactivatingPanel` still keeps the app in the background, so becoming key
/// does not pull the user out of whatever they were working in.
final class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

/// A panel that tells a click apart from a drag.
///
/// The detection sits on a local event monitor rather than on `mouseDown` /
/// `mouseUp` overrides: the SwiftUI hosting view consumes those before the
/// window ever sees them, so the overrides never fired and clicking the pill
/// did nothing. A monitor runs ahead of that dispatch and works regardless of
/// what the content view does with the event.
@MainActor
final class OverlayPanelController {
    private var panel: NSPanel?
    private var downAt: NSPoint?
    private var clickMonitor: Any?
    /// Called when the pill is clicked (not dragged).
    var onClick: (() -> Void)?
    private var frameObserver: Any?
    private static let positionKey = "overlayPanelOrigin"
    private static let size = NSSize(width: 232, height: 62)

    /// Where the pill sits, in screen coordinates — the target the window
    /// folds into and the place it springs back out of.
    var frame: NSRect { panel?.frame ?? .zero }

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
        let panel = KeyablePanel(
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
        installClickMonitor(for: panel)
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

    private func installClickMonitor(for panel: NSPanel) {
        clickMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseUp]) {
            [weak self, weak panel] event in
            guard let self, let panel, event.window === panel else { return event }
            if event.type == .leftMouseDown {
                self.downAt = NSEvent.mouseLocation
                return event
            }
            defer { self.downAt = nil }
            guard let start = self.downAt else { return event }
            let end = NSEvent.mouseLocation
            // Four points of slack: a click with a shaky hand is still a click,
            // and a drag of four points was not meant to move anything.
            if abs(end.x - start.x) < 4, abs(end.y - start.y) < 4 {
                Task { @MainActor in self.onClick?() }
            }
            return event
        }
    }

    /// Fades the pill out instead of snapping it away, so the window appears to
    /// come out of it rather than to replace it.
    func fadeOut(duration: TimeInterval, then done: @escaping () -> Void) {
        guard let panel, panel.isVisible else { done(); return }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = duration
            panel.animator().alphaValue = 0
        } completionHandler: {
            panel.orderOut(nil)
            panel.alphaValue = 1
            done()
        }
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
