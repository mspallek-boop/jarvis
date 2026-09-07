#if os(macOS)
import AppKit
import SwiftUI

/// JARVIS as a pill above the Dock: idle it is a dash you stop noticing,
/// listening it is a waveform.
///
/// Sized and placed to be ignorable. The whole value of a push-to-talk overlay
/// is that it never asks for attention between uses, so idle it shows one small
/// mark and nothing else — no label, no button, no chrome.
struct OverlayView: View {
    @EnvironmentObject private var model: AppModel

    private var ink: Color { .white }

    private var isActive: Bool {
        model.speech.isListening || model.hotkey.isHeld || model.hotkey.handsFree
    }

    var body: some View {
        HStack(spacing: 10) {
            // The same grid and the same animation as the orb, three across
            // instead of five: at this size five tiles are mush, and a
            // different shape would read as a different app.
            OrbView(active: true,
                    listening: model.speech.isListening || model.hotkey.isHeld,
                    thinking: model.isWorking,
                    size: 22, color: ink, columns: 3)
            if isActive {
                Waveform(active: model.speech.isListening || model.hotkey.isHeld, ink: ink)
                    .frame(width: 74, height: 15)
            } else if model.isWorking {
                Waveform(active: true, ink: ink.opacity(0.6))
                    .frame(width: 74, height: 15)
            } else {
                Capsule()
                    .fill(ink.opacity(0.32))
                    .frame(width: 42, height: 3)
            }
            if model.hotkey.handsFree {
                // The one thing worth a word: hands-free stays on after you let
                // go, and forgetting that means an open microphone.
                Text("frei")
                    .font(.system(size: 9, weight: .semibold, design: .rounded))
                    .foregroundStyle(ink.opacity(0.75))
            }
        }
        .padding(.horizontal, 13)
        .frame(height: 36)
        .background(
            Capsule().fill(Color.black.opacity(0.82))
                .overlay(Capsule().strokeBorder(ink.opacity(isActive ? 0.22 : 0.10), lineWidth: 1))
        )
        .animation(.easeInOut(duration: 0.18), value: isActive)
        .animation(.easeInOut(duration: 0.18), value: model.hotkey.handsFree)
        .onTapGesture { Task { await model.toggleListening() } }
        .help(model.hotkey.enabled
              ? "\(model.hotkey.key.label) halten zum Sprechen · doppelt tippen für freihändig"
              : "Tastenkürzel ist aus")
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Bars that rise and fall while listening, and lie flat when not.
private struct Waveform: View {
    let active: Bool
    let ink: Color
    @State private var phase: CGFloat = 0

    private let heights: [CGFloat] = [0.35, 0.7, 1.0, 0.55, 0.85, 0.4, 0.95, 0.6, 0.3]

    var body: some View {
        HStack(spacing: 3) {
            ForEach(heights.indices, id: \.self) { index in
                Capsule()
                    .fill(ink.opacity(0.85))
                    .frame(width: 3,
                           height: active ? bar(index) : 3)
            }
        }
        .frame(maxHeight: .infinity)
        .onAppear {
            guard active else { return }
            withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) { phase = 1 }
        }
        .onChange(of: active) { _, running in
            phase = 0
            guard running else { return }
            withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) { phase = 1 }
        }
    }

    private func bar(_ index: Int) -> CGFloat {
        let base = heights[index]
        // Alternating bars breathe out of step, which reads as sound rather
        // than as a progress bar.
        let swing = index.isMultiple(of: 2) ? phase : 1 - phase
        return 4 + 11 * base * (0.45 + 0.55 * swing)
    }
}

/// Puts the panel where a push-to-talk indicator belongs: bottom centre, just
/// above the Dock, above other apps' windows, on every Space, and never
/// stealing focus — taking focus would defeat dictating into another app.
struct OverlayWindowConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.level = .floating
            window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            window.isMovableByWindowBackground = true
            window.backgroundColor = .clear
            window.isOpaque = false
            window.hasShadow = true
            window.styleMask.remove(.resizable)
            window.standardWindowButton(.closeButton)?.isHidden = true
            window.standardWindowButton(.zoomButton)?.isHidden = true
            window.standardWindowButton(.miniaturizeButton)?.isHidden = true
            // Only place it the first time; afterwards the user's own position
            // is the right one.
            if !UserDefaults.standard.bool(forKey: "overlayPlaced"),
               let screen = window.screen ?? NSScreen.main {
                let visible = screen.visibleFrame
                let size = window.frame.size
                window.setFrameOrigin(CGPoint(
                    x: visible.midX - size.width / 2,
                    y: visible.minY + 12))
                UserDefaults.standard.set(true, forKey: "overlayPlaced")
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}
#endif
