#if os(macOS)
import AppKit

/// Clicking the Dock icon has to bring back the window that already exists.
///
/// Without a delegate, SwiftUI answers a reopen for an app with no *visible*
/// window by building a second one from the `WindowGroup`. A folded window is
/// exactly that case: ordered out, still alive, still holding the conversation.
/// So the click produced an empty duplicate while the real window stayed folded
/// — two JARVIS windows, and the wrong one in front.
///
/// Returning `false` means "handled, build nothing". The one path that still
/// returns `true` is the genuine one: no window to come back to, so let SwiftUI
/// make the first one.
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        MainActor.assumeIsolated {
            // The pill is the window folded up, so unfolding it *is* the
            // reopen. Checked first: while it is up, the main window is ordered
            // out and would otherwise be brought back behind the pill.
            if model?.overlayVisible == true {
                model?.expandFromOverlay()
                return false
            }

            guard let window = WindowTransition.mainWindow() else { return true }

            // ⌘M leaves the window in the Dock rather than ordered out, and a
            // miniaturized window ignores `makeKeyAndOrderFront` — that alone
            // looked like the reopen had done nothing.
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return false
        }
    }
}
#endif
