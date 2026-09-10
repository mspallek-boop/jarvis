import ActivityKit
import SwiftUI
import WidgetKit

/// The JARVIS mark: one tile from the app icon's grid, not the whole grid.
///
/// The 3×3 version is the app icon and it is right at app-icon size. At the
/// sixteen points the Dynamic Island gives it, nine rounded squares with gaps
/// between them stop being a mark and become texture. One tile keeps the
/// shape language — the same corner curve — and stays a shape at any size,
/// which is what lets it pulse legibly.
private struct GridGlyph: View {
    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            RoundedRectangle(cornerRadius: side * 0.28, style: .continuous)
                .frame(width: side, height: side)
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
    /// Nil on the Dynamic Island, which is a hole in the display and takes
    /// white; set on the lock screen, where the app's colour is the ground and
    /// the mark has to read against it.
    var tint: Color?
    var size: CGFloat = 18

    @Environment(\.isLuminanceReduced) private var dimmed
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var breathing = false

    private var resting: Bool { state.isFinished || state.failure != nil }
    private var still: Bool { resting || dimmed || reduceMotion }

    /// White, because that is the mark. Only a real failure takes a colour,
    /// and it takes one because it is a warning and not decoration.
    private var colour: Color {
        if state.failure != nil { return .orange }
        return tint ?? .white
    }

    var body: some View {
        GridGlyph()
            .foregroundStyle(colour)
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
            .keylineTint(context.state.failure == nil ? Color.white : Color.orange)
        }
    }
}

/// Running, done, or broken — in six points of colour and nothing else.
private struct StateDot: View {
    let state: JarvisActivityAttributes.ContentState

    private var colour: Color {
        if state.failure != nil { return .orange }
        return .white
    }

    var body: some View {
        Circle()
            .fill(colour)
            // Finished is the same mark, quieter — state without a second hue.
            .opacity(state.isFinished ? 0.45 : 1)
            .frame(width: 6, height: 6)
            .accessibilityLabel(Text(state.spokenStatus))
    }
}

/// The tile JARVIS keeps on the Home Screen and in StandBy.
///
/// StandBy is a phone on a stand, across the room, often in the dark — so this
/// is a mark, a word, and nothing else. Apple tints StandBy widgets red below
/// a light threshold (`widgets.md › rendering modes`), which is why the design
/// is monochrome: a white mark survives being turned red, a coloured one turns
/// muddy.
///
/// It cannot show live state. That needs an App Group between the app and this
/// extension, and adding one is a provisioning capability rather than a line of
/// code. A running conversation already has a better home in StandBy anyway:
/// the Live Activity, which the system scales to fill the screen when tapped.
/// This tile is the other half — the way in when nothing is running.
struct JarvisStandByWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "JarvisStandBy", provider: StandByProvider()) { _ in
            StandByTile()
                .containerBackground(.black, for: .widget)
                // Straight into listening, because the point of a phone on a
                // stand is not having to hold it and tap twice.
                .widgetURL(URL(string: "jarvis://listen"))
        }
        .configurationDisplayName("JARVIS")
        .description("Tippen, um zu sprechen.")
        .supportedFamilies([.systemSmall])
    }
}

private struct StandByEntry: TimelineEntry {
    let date: Date
}

private struct StandByProvider: TimelineProvider {
    func placeholder(in context: Context) -> StandByEntry { StandByEntry(date: .now) }

    func getSnapshot(in context: Context, completion: @escaping (StandByEntry) -> Void) {
        completion(StandByEntry(date: .now))
    }

    /// Nothing here changes on its own, so there is nothing to schedule. A
    /// widget that reloads for no reason is a widget that costs battery.
    func getTimeline(in context: Context, completion: @escaping (Timeline<StandByEntry>) -> Void) {
        completion(Timeline(entries: [StandByEntry(date: .now)], policy: .never))
    }
}

private struct StandByTile: View {
    var body: some View {
        VStack(spacing: 10) {
            GridGlyph()
                .foregroundStyle(.white)
                .frame(width: 38, height: 38)
            Text("JARVIS")
                .font(.caption.weight(.semibold))
                .tracking(2)
                .foregroundStyle(.white.opacity(0.75))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityLabel("JARVIS öffnen und zuhören")
    }
}

@main
struct JarvisLiveActivityBundle: WidgetBundle {
    var body: some Widget {
        JarvisLiveActivity()
        JarvisStandByWidget()
    }
}
