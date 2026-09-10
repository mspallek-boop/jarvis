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

/// The mark, and the one thing it has to say: working, done, or broken.
///
/// The breathing is the only motion left, and it is switched off in the three
/// places motion is either wrong or impossible: when the turn is over, when
/// the display has dimmed to its always-on state, and when the user has asked
/// the system for less movement. A pulse that runs forever on a screen the
/// user is not looking at is decoration, and decoration is what made this
/// thing feel loud.
private struct Mark: View {
    let state: JarvisActivityAttributes.ContentState
    /// Nil on the Dynamic Island, which is a hole in the display and takes the
    /// system accent; set on the lock screen, where the app's colour is ground.
    var tint: Color?
    var size: CGFloat = 18

    @Environment(\.isLuminanceReduced) private var dimmed
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var breathing = false

    private var resting: Bool { state.isFinished || state.failure != nil }
    private var still: Bool { resting || dimmed || reduceMotion }

    var body: some View {
        GridGlyph()
            .foregroundStyle(state.failure != nil ? Color.orange
                             : (tint ?? (state.isFinished ? Color.secondary : Color.accentColor)))
            .frame(width: size, height: size)
            .opacity(still ? 1 : (breathing ? 1 : 0.5))
            .animation(still ? nil : .easeInOut(duration: 1.4).repeatForever(autoreverses: true),
                       value: breathing)
            .onAppear { breathing = true }
            .accessibilityLabel(Text(state.spokenStatus))
    }
}

/// Where the turn stands, in one line and at a weight that survives a glance.
///
/// `live-activities.md › Best practices`: "Use large, heavier-weight text — a
/// medium weight or higher." The old caption-sized secondary text failed that
/// twice over.
private struct PhaseLine: View {
    let state: JarvisActivityAttributes.ContentState
    var tint: Color?
    var font: Font = .footnote

    var body: some View {
        Text(state.failure ?? (state.isFinished ? "Fertig" : state.phase))
            .font(font.weight(.medium))
            .foregroundStyle(state.failure == nil ? (tint ?? Color.primary) : Color.orange)
            .lineLimit(1)
    }
}

/// The lock screen, the Notification Center banner, and — scaled up — StandBy.
///
/// What is on it, and what deliberately is not: the state, always; the
/// question and the answer, only to someone who has unlocked the phone.
/// `privacySensitive()` is the system's own answer to that, and it is the
/// right one here because JARVIS reads messages, calendars and files aloud.
/// Anyone standing near a phone on a charging stand would otherwise read them
/// too — and StandBy is exactly that situation, all evening.
private struct LockScreenView: View {
    let context: ActivityViewContext<JarvisActivityAttributes>

    private var ground: Color { ActivityPalette.background(context.attributes.background) }
    private var ink: Color { ActivityPalette.foreground(context.attributes.background) }
    private var quiet: Color { ActivityPalette.secondary(context.attributes.background) }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Mark(state: context.state, tint: ink, size: 20)
            VStack(alignment: .leading, spacing: 3) {
                PhaseLine(state: context.state, tint: ink, font: .subheadline)
                if !context.attributes.prompt.isEmpty {
                    Text(context.attributes.prompt)
                        .font(.footnote)
                        .foregroundStyle(quiet)
                        .lineLimit(1)
                        .privacySensitive()
                }
                if !context.state.replyExcerpt.isEmpty {
                    Text(context.state.replyExcerpt)
                        .font(.footnote)
                        .foregroundStyle(quiet)
                        .lineLimit(2)
                        .privacySensitive()
                }
            }
            Spacer(minLength: 0)
        }
        // Concentric with the banner's own corner, per `live-activities.md ›
        // Creating Live Activity layouts`, rather than a flat box of padding.
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
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
                    Mark(state: context.state, size: 20)
                        .padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    PhaseLine(state: context.state)
                        .padding(.trailing, 4)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    // Expanded means the user is holding it open, so the
                    // question may show — still redacted while locked.
                    if !context.attributes.prompt.isEmpty {
                        Text(context.attributes.prompt)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .privacySensitive()
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            } compactLeading: {
                Mark(state: context.state, size: 16)
            } compactTrailing: {
                // A dot, not a word. The old version cut the phase down to its
                // first verb — "denke", "suche" — which is a fragment of German
                // sitting in the notch, and the single loudest thing about the
                // old design. State is all the compact presentation owes you;
                // the words are two millimetres away in the expanded view.
                StateDot(state: context.state)
            } minimal: {
                Mark(state: context.state, size: 16)
            }
            .keylineTint(context.state.failure == nil ? Color.accentColor : Color.orange)
        }
    }
}

/// Running, done, or broken — in six points of colour and nothing else.
private struct StateDot: View {
    let state: JarvisActivityAttributes.ContentState

    private var colour: Color {
        if state.failure != nil { return .orange }
        return state.isFinished ? .secondary : .accentColor
    }

    var body: some View {
        Circle()
            .fill(colour)
            .frame(width: 6, height: 6)
            .accessibilityLabel(Text(state.spokenStatus))
    }
}

@main
struct JarvisLiveActivityBundle: WidgetBundle {
    var body: some Widget {
        JarvisLiveActivity()
    }
}
