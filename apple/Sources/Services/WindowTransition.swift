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
    private static let collapse: TimeInterval = 0.24
    private static let expand: TimeInterval = 0.42

    /// Accelerating away: slow to leave, then gone. Nothing to read on the way
    /// out, so it need not settle.
    static let leaving = CAMediaTimingFunction(controlPoints: 0.45, 0, 0.9, 0.35)
    /// Arriving with a small overshoot past 1 — that is the "pop", and it is
    /// what a spring does that an ease-out cannot. Shared with the pill's own
    /// arrival from the Dock: two things that both mean "here I am" must move
    /// the same way, or the app has two accents.
    static let arriving = CAMediaTimingFunction(controlPoints: 0.22, 1.2, 0.36, 1)
    private static let restoredKey = "mainWindowFrameBeforeCollapse"

    private static var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }

    /// Held from the moment it folds up.
    ///
    /// Searching `NSApp.windows` at restore time returned nil — an ordered-out
    /// window is not reliably findable that way, and everything upstream worked
    /// while this one lookup silently failed. Remembering the window we just
    /// animated cannot fail for that reason; the search stays only as a
    /// fallback for a first restore after launch.
    private static weak var collapsed: NSWindow?

    static func mainWindow() -> NSWindow? {
        collapsed ?? NSApp.windows.first {
            !($0 is NSPanel) && $0.canBecomeMain && $0.contentView != nil
        }
    }

    /// Fold the window down into the pill, then hand over.
    static func collapse(into target: NSRect, then finish: @escaping () -> Void) {
        guard let window = mainWindow(), window.isVisible else { finish(); return }
        collapsed = window
        remember(window.frame)
        guard !reduceMotion else {
            window.orderOut(nil)
            finish()
            return
        }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = collapse
            context.timingFunction = leaving
            window.animator().setFrame(target, display: true)
            // Not to zero: a window that is still faintly there when it reaches
            // the pill hands over to it, instead of blinking out beforehand.
            window.animator().alphaValue = 0.35
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
    static var expandDuration: TimeInterval { expand }

    static func expand(from source: NSRect) {
        guard let window = mainWindow() else { return }
        // ⌘M leaves the window in the Dock rather than ordered out, and a
        // miniaturized window ignores every order-front there is. Undoing that
        // first is what makes the ⌘M path restore at all.
        if window.isMiniaturized { window.deminiaturize(nil) }
        let destination = centredFrame(for: window, on: source)
        guard !reduceMotion else {
            window.setFrame(destination, display: true)
            window.makeKeyAndOrderFront(nil)
            return
        }
        // Starts visible rather than transparent: a window that fades in while
        // it grows reads as two effects; growing alone reads as one movement.
        window.alphaValue = 0.6
        window.setFrame(source, display: false)
        window.makeKeyAndOrderFront(nil)
        NSAnimationContext.runAnimationGroup { context in
            context.duration = expand
            context.timingFunction = arriving
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
