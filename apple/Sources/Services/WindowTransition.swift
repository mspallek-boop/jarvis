#if os(macOS)
import AppKit

/// The window collapsing into the pill and springing back out of it.
///
/// Both directions animate the *same* rectangle between the same two places, so
/// the pill reads as the window folded up rather than as a separate thing that
/// replaced it — spatial continuity is the whole point, and without it the
/// window simply vanishes and something else appears.
///
/// Timing follows the usual asymmetry: leaving accelerates and is short, because
/// the user already decided; arriving decelerates and takes a little longer,
/// because they are about to read it. Reduced motion skips straight to the end
/// state — the transition is decoration, never information.
@MainActor
enum WindowTransition {
    private static let collapse: TimeInterval = 0.26
    private static let expand: TimeInterval = 0.36
    private static let restoredKey = "mainWindowFrameBeforeCollapse"

    private static var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }

    static func mainWindow() -> NSWindow? {
        NSApp.windows.first { !($0 is NSPanel) && $0.canBecomeMain && $0.contentView != nil }
    }

    /// Fold the window down into the pill, then hand over.
    static func collapse(into target: NSRect, then finish: @escaping () -> Void) {
        guard let window = mainWindow(), window.isVisible else { finish(); return }
        remember(window.frame)
        guard !reduceMotion else {
            window.orderOut(nil)
            finish()
            return
        }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = collapse
            // Leaving: accelerate away.
            context.timingFunction = CAMediaTimingFunction(name: .easeIn)
            window.animator().setFrame(target, display: true)
            window.animator().alphaValue = 0
        } completionHandler: {
            window.orderOut(nil)
            // Put the frame back before the window is next shown, or the
            // restore would start from a pill-sized window.
            window.setFrame(remembered() ?? window.frame, display: false)
            window.alphaValue = 1
            finish()
        }
    }

    /// Spring back out of the pill, centred on the screen it sits on.
    static func expand(from source: NSRect) {
        guard let window = mainWindow() else { return }
        let destination = centredFrame(for: window, on: source)
        guard !reduceMotion else {
            window.setFrame(destination, display: true)
            window.makeKeyAndOrderFront(nil)
            return
        }
        window.alphaValue = 0
        window.setFrame(source, display: false)
        window.makeKeyAndOrderFront(nil)
        NSAnimationContext.runAnimationGroup { context in
            context.duration = expand
            // Arriving: decelerate into place.
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            window.animator().setFrame(destination, display: true)
            window.animator().alphaValue = 1
        }
    }

    /// The size the window had before it folded up, centred — "back to normal"
    /// means the size the user was working with, not whatever fits.
    private static func centredFrame(for window: NSWindow, on source: NSRect) -> NSRect {
        let screen = NSScreen.screens.first { $0.frame.intersects(source) } ?? NSScreen.main
        let visible = screen?.visibleFrame ?? source
        var size = remembered()?.size ?? window.frame.size
        size.width = min(size.width, visible.width - 40)
        size.height = min(size.height, visible.height - 40)
        return NSRect(x: visible.midX - size.width / 2,
                      y: visible.midY - size.height / 2,
                      width: size.width, height: size.height)
    }

    private static func remember(_ frame: NSRect) {
        storeFrame([frame.origin.x, frame.origin.y, frame.width, frame.height])
    }

    private static func storeFrame(_ values: [Double]) {
        UserDefaults.standard.set(values, forKey: restoredKey)
    }

    private static func remembered() -> NSRect? {
        guard let v = UserDefaults.standard.array(forKey: restoredKey) as? [Double], v.count == 4,
              v[2] > 200, v[3] > 200 else { return nil }
        return NSRect(x: v[0], y: v[1], width: v[2], height: v[3])
    }
}
#endif
