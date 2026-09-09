import ActivityKit
import SwiftUI
import WidgetKit

/// The JARVIS mark, drawn as a vector so it stays sharp from an 8-point
/// Dynamic Island glyph up to the lock screen. Same 3×3 grid as the app icon.
private struct GridGlyph: View {
    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            let tile = side / 3.36
            let gap = tile * 0.18
            VStack(spacing: gap) {
                ForEach(0..<3, id: \.self) { _ in
                    HStack(spacing: gap) {
                        ForEach(0..<3, id: \.self) { _ in
                            RoundedRectangle(cornerRadius: tile * 0.23, style: .continuous)
                                .frame(width: tile, height: tile)
                        }
                    }
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
    }
}

/// A quiet pulse while work is happening, and stillness when it is not.
/// Motion on a lock screen has to earn itself: it is the one signal that says
/// "still running" without any words.
private struct StatusGlyph: View {
    let finished: Bool
    let failed: Bool
    /// Nil on the Dynamic Island, which is always black and takes the system
    /// accent; set on the lock screen, where the app's own colour is the ground.
    var tint: Color?
    @State private var breathing = false

    var body: some View {
        GridGlyph()
            .foregroundStyle(failed ? Color.orange : (tint ?? (finished ? Color.secondary : Color.accentColor)))
            .frame(width: 22, height: 22)
            .opacity(finished || failed ? 1 : (breathing ? 1 : 0.45))
            .animation(finished || failed ? nil
                       : .easeInOut(duration: 1.1).repeatForever(autoreverses: true),
                       value: breathing)
            .onAppear { breathing = true }
    }
}

/// One line that says where the turn stands. The phase while it runs, the
/// reason while it is broken, and nothing self-congratulatory when it is done.
private struct PhaseLine: View {
    let state: JarvisActivityAttributes.ContentState
    var tint: Color?

    var body: some View {
        Text(state.failure ?? (state.isFinished ? "Fertig" : state.phase))
            .font(.caption)
            .foregroundStyle(state.failure == nil ? (tint ?? Color.secondary) : Color.orange)
            .lineLimit(1)
    }
}

/// The lock screen and the Notification Center banner.
private struct LockScreenView: View {
    let context: ActivityViewContext<JarvisActivityAttributes>

    private var ground: Color { ActivityPalette.background(context.attributes.background) }
    private var ink: Color { ActivityPalette.foreground(context.attributes.background) }
    private var quiet: Color { ActivityPalette.secondary(context.attributes.background) }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            StatusGlyph(finished: context.state.isFinished,
                        failed: context.state.failure != nil, tint: ink)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 4) {
                Text(context.attributes.prompt)
                    .font(.footnote.weight(.medium))
                    .lineLimit(1)
                    .foregroundStyle(quiet)
                // The answer is the reason to look at the screen, so it gets
                // the size — until there is one, the phase stands in for it.
                if context.state.replyExcerpt.isEmpty {
                    PhaseLine(state: context.state, tint: ink)
                        .font(.callout)
                } else {
                    Text(context.state.replyExcerpt)
                        .font(.callout)
                        .foregroundStyle(ink)
                        .lineLimit(4)
                    PhaseLine(state: context.state, tint: quiet)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        // The lock screen wears the colour the user chose in the app, so the
        // two read as one thing. The Dynamic Island deliberately does not:
        // it is a hole in the display, and a coloured one looks like a bug.
        .activityBackgroundTint(ground)
        .activitySystemActionForegroundColor(ink)
    }
}

struct JarvisLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: JarvisActivityAttributes.self) { context in
            LockScreenView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    StatusGlyph(finished: context.state.isFinished,
                                failed: context.state.failure != nil)
                        .padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    PhaseLine(state: context.state)
                        .padding(.trailing, 4)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(context.attributes.prompt)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                        if !context.state.replyExcerpt.isEmpty {
                            Text(context.state.replyExcerpt)
                                .font(.callout)
                                .lineLimit(3)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } compactLeading: {
                StatusGlyph(finished: context.state.isFinished,
                            failed: context.state.failure != nil)
                    .frame(width: 18, height: 18)
            } compactTrailing: {
                // Compact has room for a word, not a sentence. The first one
                // of the phase is the one that carries it: "Ich denke nach"
                // reads as "denke", which is exactly what a glance needs.
                Text(compactWord(for: context.state))
                    .font(.caption2)
                    .lineLimit(1)
            } minimal: {
                StatusGlyph(finished: context.state.isFinished,
                            failed: context.state.failure != nil)
                    .frame(width: 16, height: 16)
            }
            .keylineTint(context.state.failure == nil ? Color.accentColor : Color.orange)
        }
    }

    private func compactWord(for state: JarvisActivityAttributes.ContentState) -> String {
        if state.failure != nil { return "Fehler" }
        if state.isFinished { return "fertig" }
        // Drop a leading "Ich " so the verb survives the truncation.
        let phase = state.phase.hasPrefix("Ich ")
            ? String(state.phase.dropFirst(4))
            : state.phase
        return String(phase.split(separator: " ").first ?? "läuft")
    }
}

@main
struct JarvisLiveActivityBundle: WidgetBundle {
    var body: some Widget {
        JarvisLiveActivity()
    }
}
