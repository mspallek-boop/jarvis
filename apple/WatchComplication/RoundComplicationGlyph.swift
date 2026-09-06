import SwiftUI

enum RoundComplicationStyle: CaseIterable {
    case orbit, voice, minimal

    var title: String {
        switch self {
        case .orbit: return "Orbit"
        case .voice: return "Stimme"
        case .minimal: return "Minimal"
        }
    }
}

/// Decorative launcher marks, never a simulated connection or progress gauge.
/// Proportional strokes keep the same silhouette in circular and corner slots.
struct RoundComplicationGlyph: View {
    let style: RoundComplicationStyle

    var body: some View {
        GeometryReader { geometry in
            let side = min(geometry.size.width, geometry.size.height)
            ZStack {
                switch style {
                case .orbit:
                    Circle().strokeBorder(lineWidth: side * 0.035)
                        .opacity(0.4)
                    ForEach(0..<3, id: \.self) { segment in
                        Circle().trim(from: 0.035, to: 0.285)
                            .stroke(style: StrokeStyle(lineWidth: side * 0.065, lineCap: .round))
                            .rotationEffect(.degrees(Double(segment) * 120 - 90))
                            .padding(side * 0.14)
                    }
                    Circle().frame(width: side * 0.22, height: side * 0.22)
                case .voice:
                    Circle().strokeBorder(lineWidth: side * 0.035)
                        .opacity(0.4)
                    HStack(spacing: side * 0.065) {
                        ForEach(Array([0.20, 0.38, 0.56, 0.38, 0.20].enumerated()), id: \.offset) { _, height in
                            Capsule().frame(width: side * 0.065, height: side * height)
                        }
                    }
                case .minimal:
                    Circle().strokeBorder(lineWidth: side * 0.025)
                        .opacity(0.3)
                    Text("J")
                        .font(.system(size: side * 0.64, weight: .light, design: .rounded))
                        .offset(x: side * 0.015, y: -side * 0.015)
                }
            }
            .frame(width: side, height: side)
            .frame(width: geometry.size.width, height: geometry.size.height)
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityHidden(true)
    }
}
