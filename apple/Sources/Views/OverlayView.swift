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
            // Motion means work. The grid moves while JARVIS listens or thinks
            // and is perfectly still otherwise — an idle pill that keeps
            // morphing claims to be busy when it is asleep, and after the
            // hundredth time it is just something twitching in the corner.
            OrbView(active: true, listening: listening,
                    thinking: model.isWorking,
                    size: 34, color: ink, columns: 3,
                    ignoresScenePhase: true)
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
            // A button, not a tap on the whole panel: the rest of the surface
            // has to stay free, or dragging the panel starts a conversation.
            Button { Task { await model.toggleListening() } } label: {
                Image(systemName: listening ? "mic.fill" : "mic")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(ink.opacity(listening ? 0.95 : 0.5))
                    .frame(width: 26, height: 26)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .focusable(false)
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
        .help(model.hotkey.enabled
              ? "\(model.hotkey.key.label) halten zum Sprechen · doppelt tippen für freihändig"
              : "Klicken zum Sprechen")
    }
}

#endif
