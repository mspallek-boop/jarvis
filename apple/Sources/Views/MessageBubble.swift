import SwiftUI

struct MessageBubble: View {
    let message: ChatMessage

    @EnvironmentObject private var model: AppModel

    private var ink: Color {
        model.backgroundChoice.foregroundColor
    }

    @ViewBuilder
    var body: some View {
        if message.role == .system {
            HStack {
                Text(message.text)
                    .font(model.appFont(.caption))
                    .foregroundStyle(ink.opacity(0.5))
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
            }
            .padding(.vertical, 10)
        } else {
            HStack {
            if message.role == .user { Spacer(minLength: 42) }
            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 7) {
                Text(message.role == .jarvis ? "JARVIS" : message.role == .user ? "YOU" : "SYSTEM")
                    .font(model.appFont(.caption2, weight: .semibold))
                    .tracking(1.5)
                    .foregroundStyle(ink.opacity(0.44))
                Text(message.role == .jarvis ? AnswerText.formatted(message.text) : AttributedString(message.text))
                    .font(model.appFont(.body))
                    .multilineTextAlignment(message.role == .user ? .trailing : .leading)
                    .textSelection(.enabled)
                    .foregroundStyle(ink.opacity(0.92))
                if !message.attachments.isEmpty {
                    AttachmentStrip(attachments: message.attachments, ink: ink)
                }
                if !message.tools.isEmpty {
                    Text(message.tools.joined(separator: " · ").uppercased())
                        .font(model.appFont(.caption2))
                        .foregroundStyle(ink.opacity(0.42))
                }
            }
            if message.role != .user { Spacer(minLength: 42) }
            }
            .padding(16)
            .background {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(ink.opacity(message.role == .user ? 0.10 : 0.055))
            }
            .padding(.vertical, 5)
        }
    }
}


/// Pictures, clips and the pages an answer came from, shown under it.
struct AttachmentStrip: View {
    let attachments: [MessageAttachment]
    let ink: Color

    @EnvironmentObject private var model: AppModel

    private var pictures: [MessageAttachment] { attachments.filter { $0.kind == .image } }
    private var links: [MessageAttachment] { attachments.filter { $0.kind != .image && $0.isDisplayable } }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(pictures) { picture in
                Button { model.openPicture(picture, in: pictures) } label: {
                    InlineAttachmentImage(picture: picture, ink: ink)
                        .frame(maxWidth: .infinity, maxHeight: 320)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                .buttonStyle(PicturePressStyle())
                .accessibilityLabel(picture.title.isEmpty ? "Bild" : picture.title)
                .accessibilityHint("Öffnet das Bild groß")
            }
            ForEach(links) { link in
                Link(destination: URL(string: link.url) ?? URL(string: "https://example.invalid")!) {
                    HStack(spacing: 8) {
                        Image(systemName: link.kind == .video ? "play.rectangle.fill" : "link")
                            .foregroundStyle(ink.opacity(0.55))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(link.title.isEmpty ? link.host : link.title)
                                .font(model.appFont(.caption))
                                .lineLimit(1)
                            if !link.title.isEmpty, !link.host.isEmpty, link.title != link.host {
                                Text(link.host)
                                    .font(model.appFont(.caption2))
                                    .foregroundStyle(ink.opacity(0.45))
                                    .lineLimit(1)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background {
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(ink.opacity(0.07))
                    }
                }
                .buttonStyle(.plain)
                .foregroundStyle(ink.opacity(0.85))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The voice stage's pictures, under the grid folded into one row: one picture
/// as large as the stage allows (the full width on an iPhone), two or three
/// side by side and still big enough to choose from.
struct VoicePictureStage: View {
    let pictures: [MessageAttachment]
    let ink: Color

    @EnvironmentObject private var model: AppModel
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        let compact = sizeClass == .compact
        let single = pictures.count == 1
        HStack(alignment: .top, spacing: 12) {
            ForEach(Array(pictures.enumerated()), id: \.element.id) { index, picture in
                // The first starts as the grid's last rows land; the rest follow.
                Button { model.openPicture(picture, in: pictures) } label: {
                    VoicePicture(picture: picture, ink: ink, delay: 0.22 + Double(index) * 0.08)
                }
                .buttonStyle(PicturePressStyle())
                .accessibilityHint("Öffnet das Bild groß")
                .frame(maxWidth: single ? (compact ? .infinity : 420) : (compact ? 150 : 200),
                       maxHeight: single ? (compact ? 380 : 400) : 220)
            }
        }
        .padding(.horizontal, compact ? 20 : 28)
    }
}

/// One picture that unrolls downward out of the row above it — a mask growing
/// from the top edge, with a slight settle in scale — instead of popping in.
/// The frame hugs the picture itself, so there is no card around it.
struct VoicePicture: View {
    let picture: MessageAttachment
    let ink: Color
    var delay: Double = 0.22

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var image: CGImage?
    @State private var failed = false
    @State private var revealed = false

    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: 22, style: .continuous) }

    var body: some View {
        Group {
            if let image {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .aspectRatio(CGFloat(image.width) / CGFloat(max(image.height, 1)), contentMode: .fit)
                    .clipShape(shape)
                    .overlay { shape.stroke(ink.opacity(0.10), lineWidth: 0.5) }
                    .mask(alignment: .top) {
                        GeometryReader { geometry in
                            Rectangle().frame(height: revealed || reduceMotion ? geometry.size.height : 0)
                        }
                    }
                    .scaleEffect(revealed || reduceMotion ? 1 : 0.94, anchor: .top)
                    .opacity(revealed ? 1 : 0)
            } else if failed {
                Label("Bild nicht ladbar", systemImage: "photo")
                    .font(.caption2).foregroundStyle(ink.opacity(0.5)).padding(.vertical, 10)
            } else {
                shape.fill(ink.opacity(0.06))
                    .aspectRatio(1, contentMode: .fit)
                    .frame(maxWidth: 120)
            }
        }
        .accessibilityLabel(picture.title.isEmpty ? "Bild" : picture.title)
        .task(id: picture.url) {
            image = nil
            failed = false
            revealed = false
            do {
                let url = picture.url
                let task = Task.detached { try await InlineAttachmentImage.load(url) }
                let loaded = try await withTaskCancellationHandler(operation: {
                    try await task.value
                }, onCancel: { task.cancel() })
                try Task.checkCancellation()
                image = loaded
                withAnimation(reduceMotion ? .easeOut(duration: 0.2)
                              : .spring(response: 0.55, dampingFraction: 0.86).delay(delay)) {
                    revealed = true
                }
            } catch {
                if !Task.isCancelled { failed = true }
            }
        }
    }
}

/// Pressed feedback for a picture that opens: a small settle, no layout change.
struct PicturePressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.25, dampingFraction: 0.8), value: configuration.isPressed)
    }
}

/// A picture opened large, over the whole window.
///
/// Nobody wrote down how this should behave, so it follows what Photos and
/// Messages teach on both platforms. Tap a picture and it fills the window on
/// a dark ground. It closes the ways people already try: the × button, a tap
/// beside the picture, Escape, and on the phone a swipe down that the picture
/// follows. Two or three pictures from one answer stay together — swipe on the
/// phone, arrow keys or the chevrons on the Mac — with a "2 / 3" count. Pinch
/// or double-tap zooms. Share also covers saving to Photos.
struct PictureViewer: View {
    @Binding var viewing: AppModel.PictureViewing?

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var loaded: [String: CGImage] = [:]
    @State private var dismissProgress: CGFloat = 0
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            if let current = viewing {
                let pictures = current.pictures
                let index = min(max(current.index, 0), max(pictures.count - 1, 0))
                // Solid, as in Photos: even at 0.97 the header and the error
                // banner behind still showed through around the controls. Only
                // a swipe down lets the conversation back in, as it closes.
                Color.black
                    .opacity(1 - dismissProgress)
                    .ignoresSafeArea()
                    .contentShape(Rectangle())
                    .onTapGesture { close() }
                    .accessibilityHidden(true)
                pager(pictures: pictures, index: index)
                chrome(pictures: pictures, index: index)
                    .opacity(1 - dismissProgress)
            }
        }
        .transition(reduceMotion ? .opacity : .opacity.combined(with: .scale(scale: 0.96)))
        .animation(reduceMotion ? .easeOut(duration: 0.2) : .spring(response: 0.38, dampingFraction: 0.88),
                   value: viewing?.id)
        .focusable(viewing != nil)
        .focusEffectDisabled()
        .focused($focused)
        .onChange(of: viewing?.id) { focused = viewing != nil }
        .onKeyPress(.leftArrow) { step(-1); return .handled }
        .onKeyPress(.rightArrow) { step(1); return .handled }
        .onKeyPress(.escape) {
            guard viewing != nil else { return .ignored }
            close()
            return .handled
        }
    }

    @ViewBuilder
    private func pager(pictures: [MessageAttachment], index: Int) -> some View {
        #if os(iOS)
        TabView(selection: Binding(get: { index }, set: { viewing?.index = $0 })) {
            ForEach(Array(pictures.enumerated()), id: \.element.id) { offset, picture in
                ZoomablePicture(picture: picture, dismissProgress: $dismissProgress,
                                onLoad: { loaded[picture.id] = $0 }, onClose: close)
                    .tag(offset)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .ignoresSafeArea()
        #else
        if pictures.indices.contains(index) {
            let picture = pictures[index]
            ZoomablePicture(picture: picture, dismissProgress: $dismissProgress,
                            onLoad: { loaded[picture.id] = $0 }, onClose: close)
                .id(picture.id)
        }
        #endif
    }

    private func chrome(pictures: [MessageAttachment], index: Int) -> some View {
        VStack {
            HStack(spacing: 12) {
                if pictures.count > 1 {
                    Text("\(index + 1) / \(pictures.count)")
                        .font(.callout.monospacedDigit().weight(.medium))
                        .foregroundStyle(.white.opacity(0.85))
                        .padding(.horizontal, 14)
                        .frame(height: 36)
                        .background(.ultraThinMaterial, in: Capsule())
                        .accessibilityLabel("Bild \(index + 1) von \(pictures.count)")
                }
                Spacer()
                if pictures.indices.contains(index), let image = loaded[pictures[index].id] {
                    let title = pictures[index].title.isEmpty ? "Bild" : pictures[index].title
                    ShareLink(item: Image(decorative: image, scale: 1),
                              preview: SharePreview(title, image: Image(decorative: image, scale: 1))) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .buttonStyle(ViewerControlStyle())
                    .accessibilityLabel("Teilen oder sichern")
                }
                Button(action: close) { Image(systemName: "xmark") }
                    .buttonStyle(ViewerControlStyle())
                    .accessibilityLabel("Schließen")
            }
            .padding(.horizontal, 20)
            .padding(.top, 14)
            Spacer()
            #if os(macOS)
            if pictures.count > 1 {
                HStack(spacing: 16) {
                    Button { step(-1) } label: { Image(systemName: "chevron.left") }
                        .buttonStyle(ViewerControlStyle())
                        .disabled(index == 0)
                        .accessibilityLabel("Vorheriges Bild")
                    Button { step(1) } label: { Image(systemName: "chevron.right") }
                        .buttonStyle(ViewerControlStyle())
                        .disabled(index >= pictures.count - 1)
                        .accessibilityLabel("Nächstes Bild")
                }
                .padding(.bottom, 24)
            }
            #endif
        }
    }

    private func step(_ delta: Int) {
        guard let current = viewing else { return }
        let next = current.index + delta
        guard current.pictures.indices.contains(next) else { return }
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.25)) { viewing?.index = next }
    }

    /// Leaving is quicker than arriving, so closing never feels like waiting.
    private func close() {
        guard viewing != nil else { return }
        withAnimation(reduceMotion ? .easeOut(duration: 0.15) : .easeIn(duration: 0.2)) {
            viewing = nil
        }
        dismissProgress = 0
        loaded = [:]
    }
}

/// The round controls on the viewer: 44 points, legible on any picture.
private struct ViewerControlStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 44, height: 44)
            .background(.ultraThinMaterial, in: Circle())
            .contentShape(Circle())
            .opacity(isEnabled ? (configuration.isPressed ? 0.7 : 1) : 0.38)
    }
}

/// One picture in the viewer: pinch or double-tap to zoom, drag to pan while
/// zoomed, and at normal size a downward drag that closes the viewer.
private struct ZoomablePicture: View {
    let picture: MessageAttachment
    @Binding var dismissProgress: CGFloat
    let onLoad: (CGImage) -> Void
    let onClose: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var image: CGImage?
    @State private var failed = false
    @State private var zoom: CGFloat = 1
    @State private var settledZoom: CGFloat = 1
    @State private var pan: CGSize = .zero
    @State private var settledPan: CGSize = .zero
    @State private var dismissDrag: CGFloat = 0

    var body: some View {
        ZStack {
            // A tap beside the picture closes; the picture itself only zooms.
            Color.clear
                .contentShape(Rectangle())
                .onTapGesture { onClose() }
                .accessibilityHidden(true)
            if let image {
                Image(decorative: image, scale: 1)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: zoom > 1 ? 0 : 14, style: .continuous))
                    .scaleEffect(zoom)
                    .offset(x: pan.width, y: pan.height + dismissDrag)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 72)
                    .onTapGesture(count: 2) { toggleZoom() }
                    .simultaneousGesture(magnify)
                    .simultaneousGesture(drag)
                    .accessibilityElement()
                    .accessibilityLabel(picture.title.isEmpty ? "Bild" : picture.title)
                    .accessibilityAddTraits(.isImage)
                    .accessibilityAction(named: zoom > 1 ? "Verkleinern" : "Vergrößern") { toggleZoom() }
            } else if failed {
                Label("Bild nicht ladbar", systemImage: "photo")
                    .foregroundStyle(.white.opacity(0.7))
            } else {
                ProgressView().tint(.white)
            }
        }
        .task(id: picture.url) {
            do {
                let url = picture.url
                let task = Task.detached { try await InlineAttachmentImage.load(url) }
                let decoded = try await withTaskCancellationHandler(operation: {
                    try await task.value
                }, onCancel: { task.cancel() })
                try Task.checkCancellation()
                image = decoded
                onLoad(decoded)
            } catch {
                if !Task.isCancelled { failed = true }
            }
        }
    }

    private var magnify: some Gesture {
        MagnifyGesture()
            .onChanged { value in zoom = min(max(settledZoom * value.magnification, 1), 4) }
            .onEnded { _ in
                settledZoom = zoom
                if zoom <= 1.01 { resetZoom() }
            }
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 14)
            .onChanged { value in
                if zoom > 1 {
                    pan = CGSize(width: settledPan.width + value.translation.width,
                                 height: settledPan.height + value.translation.height)
                } else if value.translation.height > 0,
                          abs(value.translation.height) > abs(value.translation.width) {
                    dismissDrag = value.translation.height
                    dismissProgress = min(dismissDrag / 400, 0.8)
                }
            }
            .onEnded { value in
                if zoom > 1 {
                    settledPan = pan
                    return
                }
                if dismissDrag > 140 || value.predictedEndTranslation.height > 420 {
                    onClose()
                } else {
                    withAnimation(reduceMotion ? nil : .spring(response: 0.3, dampingFraction: 0.85)) {
                        dismissDrag = 0
                        dismissProgress = 0
                    }
                }
            }
    }

    private func toggleZoom() {
        withAnimation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.85)) {
            if zoom > 1 {
                zoom = 1
                pan = .zero
            } else {
                zoom = 2.5
            }
        }
        settledZoom = zoom
        settledPan = pan
    }

    private func resetZoom() {
        withAnimation(reduceMotion ? nil : .spring(response: 0.3, dampingFraction: 0.85)) {
            zoom = 1
            pan = .zero
        }
        settledZoom = 1
        settledPan = .zero
    }
}

/// Not private: the voice stage shows the same pictures, and one loader with
/// one set of size and type limits is worth more than two that drift apart.
struct InlineAttachmentImage: View {
    let picture: MessageAttachment
    let ink: Color
    @State private var preview: CGImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let preview {
                Image(decorative: preview, scale: 1).resizable().scaledToFit()
            } else if failed {
                Label("Bild nicht ladbar", systemImage: "photo")
                    .font(.caption2).foregroundStyle(ink.opacity(0.5)).padding(.vertical, 10)
            } else {
                ProgressView().tint(ink).frame(height: 60)
            }
        }
        .task(id: picture.url) {
            preview = nil
            failed = false
            do {
                let url = picture.url
                // Decode away from the UI actor; cancellation follows the view.
                let task = Task.detached { try await Self.load(url) }
                let image = try await withTaskCancellationHandler(operation: {
                    try await task.value
                }, onCancel: { task.cancel() })
                try Task.checkCancellation()
                preview = image
            } catch {
                if !Task.isCancelled { failed = true }
            }
        }
    }

    /// Shared with the voice stage's picture reveal: one loader, one set of limits.
    static func load(_ reference: String) async throws -> CGImage {
        var data: Data
        if reference.hasPrefix("data:") {
            guard let decoded = InlineImageData.decode(reference) else { throw URLError(.cannotDecodeContentData) }
            data = decoded
        } else {
            guard let url = URL(string: reference),
                  ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
                  url.host != nil else { throw URLError(.unsupportedURL) }
            // Public image downloads carry neither the bridge token nor cookies.
            let config = URLSessionConfiguration.ephemeral
            config.httpShouldSetCookies = false
            config.timeoutIntervalForRequest = 30
            let session = URLSession(configuration: config)
            defer { session.invalidateAndCancel() }
            let (bytes, response) = try await session.bytes(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  InlineImageData.mimeTypes.contains(http.mimeType ?? ""),
                  http.expectedContentLength <= InlineImageData.maxBytes else {
                throw URLError(.cannotDecodeContentData)
            }
            data = Data()
            for try await byte in bytes {
                try Task.checkCancellation()
                guard data.count < InlineImageData.maxBytes else { throw URLError(.dataLengthExceedsMaximum) }
                data.append(byte)
            }
        }
        try Task.checkCancellation()
        guard let image = PlatformImage.inlinePreview(from: data) else { throw URLError(.cannotDecodeContentData) }
        return image
    }
}
