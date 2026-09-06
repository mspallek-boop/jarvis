import SwiftUI
import WidgetKit

/// Static launcher complication. It carries no data, so a single entry that
/// never refreshes is enough - tapping it opens the JARVIS watch app.
private struct LaunchEntry: TimelineEntry {
    let date: Date
}

private struct LaunchProvider: TimelineProvider {
    func placeholder(in context: Context) -> LaunchEntry {
        LaunchEntry(date: .now)
    }

    func getSnapshot(in context: Context, completion: @escaping (LaunchEntry) -> Void) {
        completion(LaunchEntry(date: .now))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<LaunchEntry>) -> Void) {
        completion(Timeline(entries: [LaunchEntry(date: .now)], policy: .never))
    }
}

/// The app icon's 3x3 grid, redrawn as a vector so it stays sharp and tintable
/// at complication sizes. Ratios are taken from Resources/watchOS AppIcon-1024.
private struct GridGlyph: View {
    private let gapRatio: CGFloat = 0.18
    private let cornerRatio: CGFloat = 0.23

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            let tile = side / (3 + 2 * gapRatio)
            let gap = tile * gapRatio

            VStack(spacing: gap) {
                ForEach(0..<3, id: \.self) { _ in
                    HStack(spacing: gap) {
                        ForEach(0..<3, id: \.self) { _ in
                            RoundedRectangle(cornerRadius: tile * cornerRatio, style: .continuous)
                                .frame(width: tile, height: tile)
                        }
                    }
                }
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

private struct LaunchComplicationView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        content
            .widgetAccentable()
            .containerBackground(.clear, for: .widget)
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .accessoryInline:
            // Inline complications are text only; a glyph would be dropped.
            Text("JARVIS")
        case .accessoryRectangular:
            HStack(spacing: 8) {
                GridGlyph()
                    .frame(width: 26, height: 26)
                Text("JARVIS")
                    .font(.headline)
                Spacer(minLength: 0)
            }
        default:
            // .accessoryCircular and .accessoryCorner both want the bare mark.
            GridGlyph()
                .padding(2)
        }
    }
}

struct JARVISLaunchComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "at.marlon.jarvis.watch.launch", provider: LaunchProvider()) { _ in
            LaunchComplicationView()
        }
        .configurationDisplayName("JARVIS")
        .description("Öffnet JARVIS direkt vom Zifferblatt.")
        .supportedFamilies([
            .accessoryCircular,
            .accessoryCorner,
            .accessoryInline,
            .accessoryRectangular
        ])
    }
}

private struct RoundComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let style: RoundComplicationStyle

    var body: some View {
        RoundComplicationGlyph(style: style)
            .padding(family == .accessoryCorner ? 1 : 3)
            .widgetAccentable()
            // watchOS curves this label to fit the actual face. For circular
            // slots it appears only where the face supports an outer label.
            .widgetLabel { Text(style == .voice ? "SPRECHEN" : "JARVIS") }
            .containerBackground(.clear, for: .widget)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("JARVIS \(style.title): Sprachmodus öffnen")
    }
}

struct JARVISOrbitComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "at.marlon.jarvis.watch.orbit", provider: LaunchProvider()) { _ in
            RoundComplicationView(style: .orbit)
        }
        .configurationDisplayName("JARVIS · Orbit")
        .description("Ein feiner Reaktorring für runde Plätze und Zifferblattecken. Öffnet JARVIS.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner])
    }
}

struct JARVISVoiceComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "at.marlon.jarvis.watch.voice", provider: LaunchProvider()) { _ in
            RoundComplicationView(style: .voice)
        }
        .configurationDisplayName("JARVIS · Stimme")
        .description("Eine Sprachwelle im Kreis. Tippen öffnet den Sprachmodus.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner])
    }
}

struct JARVISMinimalComplication: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "at.marlon.jarvis.watch.minimal", provider: LaunchProvider()) { _ in
            RoundComplicationView(style: .minimal)
        }
        .configurationDisplayName("JARVIS · Minimal")
        .description("Ein dezentes J mit dünner Kreislinie für schlichte, runde Zifferblätter.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner])
    }
}

@main
struct JARVISComplicationBundle: WidgetBundle {
    var body: some Widget {
        JARVISLaunchComplication()
        JARVISOrbitComplication()
        JARVISVoiceComplication()
        JARVISMinimalComplication()
    }
}

#Preview("Orbit · Kreis", as: .accessoryCircular) {
    JARVISOrbitComplication()
} timeline: { LaunchEntry(date: .now) }

#Preview("Stimme · Ecke", as: .accessoryCorner) {
    JARVISVoiceComplication()
} timeline: { LaunchEntry(date: .now) }

#Preview("Minimal · Kreis", as: .accessoryCircular) {
    JARVISMinimalComplication()
} timeline: { LaunchEntry(date: .now) }
