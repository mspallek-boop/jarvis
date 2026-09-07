#if os(macOS)
import SwiftUI
import AppKit

/// JARVIS as a small panel that stays above other windows.
///
/// The point is to keep talking while working in something else, so it carries
/// only what a conversation needs: the orb, one line of status, the running
/// tasks. No history, no composer, no settings — those are what the main window
/// is for, and putting them here would make a second app rather than a corner
/// of this one.
struct OverlayView: View {
    @EnvironmentObject private var model: AppModel

    private var ink: Color { model.backgroundChoice.foregroundColor }

    private var label: String {
        if model.speech.microphoneMuted { return "Mikrofon stumm" }
        if model.speech.isSpeaking { return "Klicken zum Unterbrechen" }
        if model.isWorking { return model.activityLabel }
        if model.speech.isListening { return "Ich höre zu" }
        return "Klicken zum Sprechen"
    }

    var body: some View {
        ZStack {
            model.backgroundChoice.color
            VStack(spacing: 10) {
                if model.localRuns.count > 1 {
                    HStack(spacing: 10) {
                        ForEach(model.localRuns.filter { $0.id != model.focusedRunID }) { run in
                            Button { model.focusRun(run.id) } label: {
                                TaskBlobView(size: 16, color: ink, seed: run.id.hashValue)
                                    .opacity(0.55)
                                    .frame(width: 26, height: 26)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .focusable(false)
                            .help(String(run.prompt.prefix(80)))
                        }
                    }
                }
                Button { Task { await model.toggleListening() } } label: {
                    OrbView(active: model.connection == .online || model.speech.isSpeaking,
                            listening: model.speech.isListening,
                            thinking: model.isWorking,
                            size: 74, color: ink)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .focusable(false)
                .accessibilityLabel(label)
                Text(label)
                    .font(.caption2.monospaced())
                    .tracking(1.1)
                    .foregroundStyle(ink.opacity(0.5))
                    .lineLimit(1)
            }
            .padding(.vertical, 16)
        }
        .frame(minWidth: 180, minHeight: 160)
        // Dragging anywhere moves it: a floating panel with no title bar has
        // nowhere else to grab. `isMovableByWindowBackground` on the NSWindow
        // does this on every macOS version the app supports, where SwiftUI's
        // WindowDragGesture would need macOS 15.
    }
}

/// Lifts the panel above other apps' windows and keeps it there.
///
/// SwiftUI's `.windowLevel` only arrived in macOS 15, and this app targets
/// further back, so the level is set on the NSWindow itself once it exists.
struct FloatingWindowConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.level = .floating
            window.collectionBehavior.insert(.canJoinAllSpaces)
            window.collectionBehavior.insert(.fullScreenAuxiliary)
            window.isMovableByWindowBackground = true
            window.standardWindowButton(.zoomButton)?.isHidden = true
            window.standardWindowButton(.miniaturizeButton)?.isHidden = true
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}
#endif
