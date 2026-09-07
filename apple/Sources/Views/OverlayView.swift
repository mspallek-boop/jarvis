#if os(macOS)
import AppKit
import SwiftUI

/// JARVIS shrunk to a floating panel, the way a video call keeps a small window
/// when you leave it.
///
/// The panel *is* the window: one rounded rectangle, content to the edges, no
/// container inside a container. Everything here is either the grid or one line
/// about what is happening — anything else belongs in the main window.
struct OverlayView: View {
    @EnvironmentObject private var model: AppModel

    private var ink: Color { .white }

    private var listening: Bool { model.speech.isListening || model.hotkey.isHeld }

    private var status: String {
        if model.speech.microphoneMuted { return "stumm" }
        if model.hotkey.handsFree { return "freihändig" }
        if listening { return "hört zu" }
        if model.isWorking { return model.activityLabel }
        if model.speech.isSpeaking { return "spricht" }
        return model.hotkey.enabled ? model.hotkey.key.shortLabel : "bereit"
    }

    var body: some View {
        HStack(spacing: 12) {
            // Always animating, just slower when idle. A still grid reads as a
            // dead screenshot, which is what made the first version look broken.
            OrbView(active: true, listening: listening,
                    thinking: model.isWorking || !listening,
                    size: 34, color: ink, columns: 3)
                .opacity(listening || model.isWorking ? 1 : 0.6)

            VStack(alignment: .leading, spacing: 3) {
                Text(status)
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(ink.opacity(0.9))
                    .lineLimit(1)
                if model.localRuns.count > 1 {
                    Text("\(model.localRuns.count) Aufgaben")
                        .font(.system(size: 9, design: .rounded))
                        .foregroundStyle(ink.opacity(0.45))
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 17, style: .continuous)
                .fill(Color.black.opacity(0.88))
                .overlay(
                    RoundedRectangle(cornerRadius: 17, style: .continuous)
                        .strokeBorder(ink.opacity(listening ? 0.28 : 0.12), lineWidth: 1)
                )
        )
        .animation(.easeInOut(duration: 0.22), value: listening)
        .contentShape(RoundedRectangle(cornerRadius: 17, style: .continuous))
        .onTapGesture { Task { await model.toggleListening() } }
        .help(model.hotkey.enabled
              ? "\(model.hotkey.key.label) halten zum Sprechen · doppelt tippen für freihändig"
              : "Klicken zum Sprechen")
    }
}

/// Makes the window disappear as a window, and survive the app being hidden.
///
/// `canHide = false` is the whole trick. ⌘H hides *every* window an app owns,
/// so opening one at that moment shows nothing — which is why the first attempt
/// looked like it did nothing at all. This flag exempts the panel, which is
/// what makes "hidden but still listening" possible.
///
/// The window therefore exists from launch and is ordered in and out by hand,
/// rather than created on demand: a window created while the app is already
/// hiding races the hide and loses.
struct OverlayWindowConfigurator: NSViewRepresentable {
    let visible: Bool

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { configure(view.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { apply(nsView.window) }
    }

    private func configure(_ window: NSWindow?) {
        guard let window else { return }
        window.canHide = false                 // survives ⌘H — the point of all this
        window.styleMask.insert(.fullSizeContentView)
        window.styleMask.remove(.resizable)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.isMovableByWindowBackground = true
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        for button in [NSWindow.ButtonType.closeButton, .zoomButton, .miniaturizeButton] {
            window.standardWindowButton(button)?.isHidden = true
        }
        if !UserDefaults.standard.bool(forKey: "overlayPlaced"),
           let screen = window.screen ?? NSScreen.main {
            let visibleFrame = screen.visibleFrame
            let size = window.frame.size
            window.setFrameOrigin(CGPoint(x: visibleFrame.maxX - size.width - 24,
                                          y: visibleFrame.maxY - size.height - 24))
            UserDefaults.standard.set(true, forKey: "overlayPlaced")
        }
        apply(window)
    }

    private func apply(_ window: NSWindow?) {
        guard let window else { return }
        if visible {
            // Never steal focus: the user hid the app to work somewhere else.
            window.orderFrontRegardless()
        } else if window.isVisible {
            window.orderOut(nil)
        }
    }
}
#endif
