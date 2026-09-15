import ActivityKit
import SwiftUI
import WidgetKit

/// The JARVIS glyph: one tile from the app icon that morphs into the app's
/// Bauhaus glyphs, never a grid.
///
/// A grid of tiles is the app icon; in a sixteen-point hole in the display it
/// reads as texture. One tile keeps the shape language and stays legible. At
/// rest it is the rounded square of the icon; while a turn runs, every phase
/// ("Ich denke nach", "Ich suche im Web", "Ich antworte") pulls its four
/// corners into a different glyph — circle, half circle, quarter circle,
/// capsule — the same forms `BauhausTileShape` draws in the app. A finished
/// turn folds back into the square; a failure turns into an orange diamond.
///
/// Live Activities do not run open-ended animations; they animate the change
/// between two updates. That is exactly what morphing between glyphs needs.
struct TileGlyph: Hashable {
    /// Corner radii as fractions of the side: top leading, top trailing,
    /// bottom trailing, bottom leading. 0.22 everywhere is the icon's tile.
    var corners: (CGFloat, CGFloat, CGFloat, CGFloat)
    /// Width and height as fractions of the frame, for capsules and the diamond.
    var width: CGFloat = 1
    var height: CGFloat = 1
    var rotation: Double = 0

    static let square = TileGlyph(corners: (0.22, 0.22, 0.22, 0.22))
    static let circle = TileGlyph(corners: (0.5, 0.5, 0.5, 0.5))
    static let diamond = TileGlyph(corners: (0.1, 0.1, 0.1, 0.1), width: 0.72, height: 0.72, rotation: 45)

    /// The forms a running phase can take. Deliberately no plain square: that
    /// one means "at rest".
    static let working: [TileGlyph] = [
        .circle,
        TileGlyph(corners: (0.5, 0.5, 0, 0)),                     // half circle, top
        TileGlyph(corners: (0, 0.5, 0.5, 0)),                     // half circle, trailing
        TileGlyph(corners: (0, 0, 0.5, 0.5)),                     // half circle, bottom
        TileGlyph(corners: (1, 0, 0, 0)),                         // quarter, top leading
        TileGlyph(corners: (0, 0, 1, 0)),                         // quarter, bottom trailing
        TileGlyph(corners: (0.5, 0.5, 0.5, 0.5), height: 0.58),   // lying capsule
        TileGlyph(corners: (0.5, 0.5, 0.5, 0.5), width: 0.58),    // standing capsule
    ]

    static func `for`(_ state: JarvisActivityAttributes.ContentState) -> TileGlyph {
        if state.failure != nil { return .diamond }
        if state.isFinished { return .square }
        // FNV-1a over the phase: Swift's hashValue is seeded per process and
        // would give the app and the extension different glyphs.
        var hash: UInt32 = 2_166_136_261
        for byte in state.phase.utf8 { hash = (hash ^ UInt32(byte)) &* 16_777_619 }
        return working[Int(hash % UInt32(working.count))]
    }

    static func == (lhs: TileGlyph, rhs: TileGlyph) -> Bool {
        lhs.corners == rhs.corners && lhs.width == rhs.width
            && lhs.height == rhs.height && lhs.rotation == rhs.rotation
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(corners.0); hasher.combine(corners.1)
        hasher.combine(corners.2); hasher.combine(corners.3)
        hasher.combine(width); hasher.combine(height); hasher.combine(rotation)
    }
}

/// A rectangle with four independently animated corner radii — the one shape
/// every glyph above is made of, which is what lets them morph into each other.
struct TileGlyphShape: Shape {
    var corners: (CGFloat, CGFloat, CGFloat, CGFloat)

    var animatableData: AnimatablePair<AnimatablePair<CGFloat, CGFloat>, AnimatablePair<CGFloat, CGFloat>> {
        get { AnimatablePair(AnimatablePair(corners.0, corners.1), AnimatablePair(corners.2, corners.3)) }
        set { corners = (newValue.first.first, newValue.first.second, newValue.second.first, newValue.second.second) }
    }

    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        // A radius can never exceed the shorter edge, or the arcs overlap.
        func radius(_ fraction: CGFloat) -> CGFloat { min(max(fraction, 0) * side, side) }
        let (tl, tr, br, bl) = (radius(corners.0), radius(corners.1), radius(corners.2), radius(corners.3))
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + tl, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - tr, y: rect.minY))
        path.addArc(center: CGPoint(x: rect.maxX - tr, y: rect.minY + tr), radius: tr,
                    startAngle: .degrees(-90), endAngle: .degrees(0), clockwise: false)
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - br))
        path.addArc(center: CGPoint(x: rect.maxX - br, y: rect.maxY - br), radius: br,
                    startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false)
        path.addLine(to: CGPoint(x: rect.minX + bl, y: rect.maxY))
        path.addArc(center: CGPoint(x: rect.minX + bl, y: rect.maxY - bl), radius: bl,
                    startAngle: .degrees(90), endAngle: .degrees(180), clockwise: false)
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + tl))
        path.addArc(center: CGPoint(x: rect.minX + tl, y: rect.minY + tl), radius: tl,
                    startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
        path.closeSubpath()
        return path
    }
}

/// One glyph, drawn at a size in a colour.
struct TileGlyphView: View {
    let glyph: TileGlyph
    var colour: Color = .white
    var size: CGFloat

    var body: some View {
        TileGlyphShape(corners: glyph.corners)
            .fill(colour)
            .frame(width: size * glyph.width, height: size * glyph.height)
            .rotationEffect(.degrees(glyph.rotation))
            .frame(width: size, height: size)
    }
}

/// The glyph for a run's state, morphing on every update.
///
/// White, because that is the mark and the Dynamic Island is a hole in the
/// display. On the lock screen `tint` is the app's ink instead, because there
/// the app's colour is the ground. Only a real failure takes a colour of its
/// own, and it takes one because it is a warning, not decoration.
private struct Mark: View {
    let state: JarvisActivityAttributes.ContentState
    var tint: Color?
    var size: CGFloat = 18

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TileGlyphView(glyph: .for(state),
                      colour: state.failure != nil ? .orange : (tint ?? .white),
                      size: size)
            .animation(reduceMotion ? nil : .spring(duration: 0.8, bounce: 0.2), value: state)
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
                    Mark(state: context.state, size: 26)
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
                // Nothing. One glyph is the whole compact design: its form
                // already carries the state, and a second mark next to it is
                // what turned the island into a row of symbols. The words are
                // two millimetres away in the expanded view.
                EmptyView()
            } minimal: {
                Mark(state: context.state, size: 16)
            }
            .keylineTint(context.state.failure == nil ? Color.white : Color.orange)
        }
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
            TileGlyphView(glyph: .square, size: 38)
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
