import SwiftUI

private enum BauhausTileStyle: CaseIterable {
    case circle
    case semicircleTop
    case semicircleBottom
    case semicircleLeading
    case semicircleTrailing
    case quarterTopLeading
    case quarterTopTrailing
    case quarterBottomLeading
    case quarterBottomTrailing
    case horizontalCapsule
    case verticalCapsule
    case diamond

    var scale: CGSize {
        switch self {
        case .semicircleTop, .semicircleBottom:
            return CGSize(width: 1, height: 0.58)
        case .semicircleLeading, .semicircleTrailing:
            return CGSize(width: 0.58, height: 1)
        case .horizontalCapsule: return CGSize(width: 1, height: 0.58)
        case .verticalCapsule: return CGSize(width: 0.58, height: 1)
        case .diamond: return CGSize(width: 0.72, height: 0.72)
        default: return CGSize(width: 0.96, height: 0.96)
        }
    }

    var rotation: Angle {
        self == .diamond ? .degrees(45) : .zero
    }
}

private struct BauhausTileShape: Shape {
    let style: BauhausTileStyle
    var progress: CGFloat

    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }

    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        let base = side * 0.22
        let half = side * 0.5
        let full = side
        let target: (CGFloat, CGFloat, CGFloat, CGFloat)

        switch style {
        case .circle, .horizontalCapsule, .verticalCapsule:
            target = (half, half, half, half)
        case .semicircleTop:
            target = (half, half, 0, 0)
        case .semicircleBottom:
            target = (0, 0, half, half)
        case .semicircleLeading:
            target = (half, 0, 0, half)
        case .semicircleTrailing:
            target = (0, half, half, 0)
        case .quarterTopLeading:
            target = (full, 0, 0, 0)
        case .quarterTopTrailing:
            target = (0, full, 0, 0)
        case .quarterBottomLeading:
            target = (0, 0, 0, full)
        case .quarterBottomTrailing:
            target = (0, 0, full, 0)
        case .diamond:
            target = (side * 0.1, side * 0.1, side * 0.1, side * 0.1)
        }

        return roundedPath(
            in: rect,
            topLeading: interpolate(from: base, to: target.0),
            topTrailing: interpolate(from: base, to: target.1),
            bottomTrailing: interpolate(from: base, to: target.2),
            bottomLeading: interpolate(from: base, to: target.3)
        )
    }

    private func interpolate(from start: CGFloat, to end: CGFloat) -> CGFloat {
        start + (end - start) * progress
    }

    private func roundedPath(
        in rect: CGRect,
        topLeading: CGFloat,
        topTrailing: CGFloat,
        bottomTrailing: CGFloat,
        bottomLeading: CGFloat
    ) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + topLeading, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - topTrailing, y: rect.minY))
        path.addArc(
            center: CGPoint(x: rect.maxX - topTrailing, y: rect.minY + topTrailing),
            radius: topTrailing,
            startAngle: .degrees(-90),
            endAngle: .degrees(0),
            clockwise: false
        )
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - bottomTrailing))
        path.addArc(
            center: CGPoint(x: rect.maxX - bottomTrailing, y: rect.maxY - bottomTrailing),
            radius: bottomTrailing,
            startAngle: .degrees(0),
            endAngle: .degrees(90),
            clockwise: false
        )
        path.addLine(to: CGPoint(x: rect.minX + bottomLeading, y: rect.maxY))
        path.addArc(
            center: CGPoint(x: rect.minX + bottomLeading, y: rect.maxY - bottomLeading),
            radius: bottomLeading,
            startAngle: .degrees(90),
            endAngle: .degrees(180),
            clockwise: false
        )
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + topLeading))
        path.addArc(
            center: CGPoint(x: rect.minX + topLeading, y: rect.minY + topLeading),
            radius: topLeading,
            startAngle: .degrees(180),
            endAngle: .degrees(270),
            clockwise: false
        )
        path.closeSubpath()
        return path
    }
}

private struct CubeGrid: View {
    let animating: Bool

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var isBauhaus = false
    @State private var tiles = CubeGrid.makeTileStates()
    @State private var animationTask: Task<Void, Never>?

    private struct TileState {
        let style: BauhausTileStyle
        let delay: Double

        var scale: CGSize { style.scale }
        var rotation: Angle { style.rotation }
    }

    var body: some View {
        GeometryReader { geometry in
            let gridSize = min(geometry.size.width, geometry.size.height)
            let gap = gridSize * 0.026
            let tile = (gridSize - gap * 4) / 5

            ZStack {
                ForEach(0..<25, id: \.self) { index in
                    let state = tiles[index]
                    let row = index / 5
                    let column = index % 5

                    BauhausTileShape(
                        style: state.style,
                        progress: isBauhaus ? 1 : 0
                    )
                    .frame(width: tile, height: tile)
                    .scaleEffect(
                        x: isBauhaus ? state.scale.width : 1,
                        y: isBauhaus ? state.scale.height : 1
                    )
                    .rotationEffect(isBauhaus ? state.rotation : .zero)
                    .position(
                        x: tile / 2 + CGFloat(column) * (tile + gap),
                        y: tile / 2 + CGFloat(row) * (tile + gap)
                    )
                    .animation(
                        .smooth(duration: 0.58).delay(state.delay),
                        value: isBauhaus
                    )
                }
            }
            .frame(width: gridSize, height: gridSize)
        }
        .onAppear { updateAnimation() }
        .onChange(of: animating) { updateAnimation() }
        .onChange(of: reduceMotion) { updateAnimation() }
        .onChange(of: scenePhase) { updateAnimation() }
        .onDisappear {
            animationTask?.cancel()
            animationTask = nil
        }
    }

    private func updateAnimation() {
        animationTask?.cancel()
        animationTask = nil

        guard animating, !reduceMotion, scenePhase == .active else {
            isBauhaus = false
            return
        }

        animationTask = Task { @MainActor in
            while !Task.isCancelled {
                tiles = Self.makeTileStates()
                isBauhaus = true
                try? await Task.sleep(for: .milliseconds(1_250))
                guard !Task.isCancelled else { return }

                tiles = Self.withRandomDelays(tiles)
                try? await Task.sleep(for: .milliseconds(20))
                guard !Task.isCancelled else { return }
                isBauhaus = false
                try? await Task.sleep(for: .milliseconds(1_050))
            }
        }
    }

    private static func makeTileStates() -> [TileState] {
        let palette: [BauhausTileStyle] = [
            .circle, .circle, .circle, .circle, .circle,
            .semicircleTop, .semicircleTop,
            .semicircleBottom, .semicircleBottom,
            .semicircleLeading, .semicircleLeading,
            .semicircleTrailing, .semicircleTrailing,
            .quarterTopLeading, .quarterTopLeading,
            .quarterTopTrailing, .quarterTopTrailing,
            .quarterBottomLeading, .quarterBottomLeading,
            .quarterBottomTrailing, .quarterBottomTrailing,
            .horizontalCapsule, .verticalCapsule,
            .diamond, .diamond
        ]
        let styles = palette.shuffled()
        let order = Array(0..<25).shuffled()
        var delays = Array(repeating: 0.0, count: 25)
        for (rank, index) in order.enumerated() {
            delays[index] = Double(rank) * 0.018
        }
        return styles.enumerated().map { index, style in
            TileState(style: style, delay: delays[index])
        }
    }

    private static func withRandomDelays(_ states: [TileState]) -> [TileState] {
        let order = Array(states.indices).shuffled()
        var delays = Array(repeating: 0.0, count: states.count)
        for (rank, index) in order.enumerated() {
            delays[index] = Double(rank) * 0.018
        }
        return states.enumerated().map { index, state in
            TileState(style: state.style, delay: delays[index])
        }
    }
}

struct OrbView: View {
    let active: Bool
    let listening: Bool
    var thinking: Bool = false
    var size: CGFloat? = nil
    var color: Color? = nil

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var ink: Color {
        colorScheme == .dark ? .white : .black
    }

    var body: some View {
        CubeGrid(animating: listening || thinking)
            .foregroundStyle(color ?? ink)
            .opacity(active ? 1 : 0.9)
            .frame(width: gridSize, height: gridSize)
            .compositingGroup()
            .accessibilityHidden(true)
    }

    private var gridSize: CGFloat {
        size ?? (horizontalSizeClass == .compact ? 208 : 174)
    }
}
