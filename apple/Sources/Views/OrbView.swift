import SwiftUI

enum BauhausTileStyle: CaseIterable {
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

struct BauhausTileShape: Shape {
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

struct CubeGrid: View {
    let animating: Bool
    /// Tiles per side. Five is the orb; three is the overlay, where five would
    /// be mush at 30pt. The animation is identical, so both read as one thing
    /// at different sizes rather than as two designs.
    var columns: Int = 5
    /// The overlay panel lives on while the app is hidden, and a hidden app's
    /// scene is not `.active` — which froze the grid at exactly the moment it
    /// became the only thing on screen.
    var ignoresScenePhase: Bool = false
    /// Folded into its top row: the orb steps aside for a picture and stays as
    /// a header instead of vanishing. Rows fly up one after another, the lowest
    /// last, so it reads as the grid making room — not as a cut.
    var collapsed: Bool = false

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var isBauhaus = false
    @State private var tiles: [TileState] = []
    @State private var animationTask: Task<Void, Never>?

    private struct TileState {
        let style: BauhausTileStyle
        let delay: Double

        var scale: CGSize { style.scale }
        var rotation: Angle { style.rotation }
    }

    var body: some View {
        GeometryReader { geometry in
            // Folded, the height is one row — size from the width, or the
            // tiles would shrink along with it.
            let gridSize = collapsed ? geometry.size.width : min(geometry.size.width, geometry.size.height)
            let gap = gridSize * 0.026 * (5 / CGFloat(columns))
            let tile = (gridSize - gap * CGFloat(columns - 1)) / CGFloat(columns)

            ZStack {
                ForEach(0..<min(tiles.count, columns * columns), id: \.self) { index in
                    let state = tiles[index]
                    let row = index / columns
                    let column = index % columns

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
                        y: tile / 2 + CGFloat(collapsed ? 0 : row) * (tile + gap)
                    )
                    .animation(
                        .smooth(duration: 0.58).delay(state.delay),
                        value: isBauhaus
                    )
                    .animation(foldAnimation(row: row, column: column), value: collapsed)
                }
            }
            .frame(width: gridSize, height: collapsed ? tile : gridSize, alignment: .top)
        }
        .onAppear {
            if tiles.isEmpty { tiles = Self.makeTileStates(count: columns * columns) }
            updateAnimation()
        }
        .onChange(of: animating) { updateAnimation() }
        .onChange(of: reduceMotion) { updateAnimation() }
        .onChange(of: scenePhase) { updateAnimation() }
        .onDisappear {
            animationTask?.cancel()
            animationTask = nil
        }
    }

    /// Folding, the top row stays and each lower one lands a beat later with a
    /// small bounce; unfolding runs the other way, so the grid drops back down.
    private func foldAnimation(row: Int, column: Int) -> Animation {
        if reduceMotion { return .easeInOut(duration: 0.2) }
        let rank = collapsed ? row : columns - 1 - row
        return .spring(response: 0.42, dampingFraction: 0.68)
            .delay(Double(rank) * 0.045 + Double(column) * 0.012)
    }

    private func updateAnimation() {
        animationTask?.cancel()
        animationTask = nil

        guard animating, !reduceMotion, ignoresScenePhase || scenePhase == .active else {
            isBauhaus = false
            return
        }

        animationTask = Task { @MainActor in
            while !Task.isCancelled {
                tiles = Self.makeTileStates(count: columns * columns)
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

    private static func makeTileStates(count: Int = 25) -> [TileState] {
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
        // A smaller grid takes a slice of the same palette, so a three-by-three
        // never draws a shape the orb would not.
        var styles = palette.shuffled()
        while styles.count < count { styles += palette.shuffled() }
        styles = Array(styles.prefix(count))
        let order = Array(0..<count).shuffled()
        var delays = Array(repeating: 0.0, count: count)
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
    var columns: Int = 5
    var ignoresScenePhase: Bool = false
    /// One row instead of the grid, while a picture has the stage.
    var collapsed: Bool = false

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var ink: Color {
        colorScheme == .dark ? .white : .black
    }

    var body: some View {
        CubeGrid(animating: (listening || thinking) && !collapsed, columns: columns,
                 ignoresScenePhase: ignoresScenePhase, collapsed: collapsed)
            .foregroundStyle(color ?? ink)
            .opacity(active ? 1 : 0.9)
            .frame(width: gridSize, height: collapsed ? Self.rowHeight(gridSize, columns: columns) : gridSize,
                   alignment: .top)
            .animation(reduceMotion ? .easeInOut(duration: 0.2) : .spring(response: 0.5, dampingFraction: 0.82),
                       value: collapsed)
            .compositingGroup()
            .accessibilityHidden(true)
    }

    private var gridSize: CGFloat {
        size ?? (horizontalSizeClass == .compact ? 208 : 174)
    }

    /// The same arithmetic CubeGrid lays its tiles out with.
    static func rowHeight(_ gridSize: CGFloat, columns: Int = 5) -> CGFloat {
        let gap = gridSize * 0.026 * (5 / CGFloat(columns))
        return (gridSize - gap * CGFloat(columns - 1)) / CGFloat(columns)
    }
}


/// One task the split draws: a running grid or a finished one still on screen.
/// Deliberately a plain value with no reference to the model, so the grids can
/// be rendered — and their split/settle/merge animation checked — in isolation.
struct MultitaskTile: Identifiable {
    let id: String
    /// Stable glyph seed, so a tile's grid does not reshuffle when it stops.
    let seed: Int
    let running: Bool
    let failed: Bool
    let spoken: Bool
    /// The status line while running ("Ich suche im Web"), empty once done.
    let activity: String
    /// What to show below the grid: the streaming answer while running, the
    /// final answer once settled.
    let body: String
}

/// The multitasking stage: one grid per task, side by side, instead of one orb
/// with small blobs pinned around it. Several small copies of JARVIS's own grid
/// say "these separate things are happening" far more plainly than one orb does.
///
/// A running grid morphs like the orb. A finished one stops on a still glyph and
/// is drawn at full strength — saturated — while any still-running sibling dims,
/// so the eye lands on what is done. When every grid is finished and read, the
/// caller drops back to the single orb and this whole row collapses away.
struct MultitaskGrids: View {
    let tiles: [MultitaskTile]
    let focusedID: String?
    let ink: Color
    let onTap: (String) -> Void

    private var anyFinished: Bool { tiles.contains { !$0.running } }

    /// The grid shrinks as more tasks share the row, so two read large and four
    /// still fit across a phone. The single orb is ~174pt; a split grid is a
    /// small fraction of it.
    private static func side(for count: Int) -> CGFloat {
        switch count {
        case 0, 1, 2: return 132
        case 3: return 104
        default: return 78
        }
    }

    var body: some View {
        let count = tiles.count
        let side = Self.side(for: count)

        // Smaller rungs before scrolling. On an iPhone SE five tasks at 78pt
        // overflowed into the scroll view, which starts at the left edge and
        // cut the fifth grid off with nothing to say it was there. Every rung
        // is always present — an `if` here would hand ViewThatFits an empty
        // child that "fits" and show nothing.
        return ViewThatFits(in: .horizontal) {
            strip(side: side)
            strip(side: 64)
            strip(side: 52)
            strip(side: 44)
            ScrollView(.horizontal, showsIndicators: false) { strip(side: 44) }
        }
        .frame(height: side + 22)
        .frame(maxWidth: .infinity)
        .animation(.spring(response: 0.55, dampingFraction: 0.82), value: tiles.map(\.id))
        .animation(.easeInOut(duration: 0.45), value: anyFinished)
    }

    /// One row of grids at one size. The gap tightens with the grids so small
    /// rungs gain real width instead of keeping the large layout's air.
    private func strip(side: CGFloat) -> some View {
        HStack(spacing: side >= 78 ? 18 : 10) {
            ForEach(tiles) { tile in
                grid(for: tile, side: side)
            }
        }
        .padding(.horizontal, 8)
    }

    private func grid(for tile: MultitaskTile, side: CGFloat) -> some View {
        let finished = !tile.running
        // A live task next to a finished one steps back so the finished answer
        // reads first; otherwise the focused grid leads and the rest sit close.
        let dimmed = anyFinished && tile.running
        let opacity: Double = finished ? 1 : (dimmed ? 0.3 : (tile.id == focusedID ? 1 : 0.88))
        // Small 3x3 rasters, not the orb's five-by-five: fewer, larger tiles
        // read cleanly at this size and say "a piece of what it's doing".
        return CubeGrid(animating: tile.running, columns: 3)
            .foregroundStyle(tile.failed ? ink.opacity(0.45) : ink)
            .frame(width: side, height: side)
            .scaleEffect(tile.id == focusedID ? 1 : 0.96)
            .opacity(opacity)
            .overlay(alignment: .bottom) {
                // A quiet underline under the focused grid, so a tap shows a
                // result at once — before the text below has swapped.
                Capsule()
                    .fill(ink.opacity(tile.id == focusedID ? 0.5 : 0))
                    .frame(width: side * 0.34, height: 2)
                    .offset(y: 12)
            }
            .contentShape(Rectangle())
            .onTapGesture { onTap(tile.id) }
            .transition(.scale(scale: 0.55).combined(with: .opacity))
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel(finished ? (tile.failed ? "Aufgabe fehlgeschlagen" : "Aufgabe fertig") : "Aufgabe läuft")
    }
}

/// A single task, as one tile of the orb's own language: a rounded square that
/// morphs into one of the glyphs and back.
///
/// Not a small CubeGrid. A grid says "a JARVIS", and there is one JARVIS; a
/// single tile says "a piece of what it is doing", which is what a running task
/// is. It also stays legible at 34pt, where a five-by-five grid is mush.
struct TaskBlobView: View {
    var size: CGFloat = 34
    var color: Color = .primary
    /// Each blob gets its own glyph and its own phase, so a row of them reads
    /// as several things happening rather than one thing repeated.
    var seed: Int = 0

    @State private var morphed = false

    private var style: BauhausTileStyle {
        let all = BauhausTileStyle.allCases
        return all[abs(seed) % all.count]
    }

    var body: some View {
        BauhausTileShape(style: style, progress: morphed ? 1 : 0)
            .fill(color)
            .frame(width: size, height: size)
            .onAppear {
                withAnimation(
                    .easeInOut(duration: 1.6)
                    .repeatForever(autoreverses: true)
                    .delay(Double(abs(seed) % 5) * 0.24)
                ) { morphed = true }
            }
            .accessibilityHidden(true)
    }
}
