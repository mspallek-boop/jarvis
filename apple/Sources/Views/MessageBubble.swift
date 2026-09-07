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
                InlineAttachmentImage(picture: picture, ink: ink)
                .frame(maxWidth: .infinity, maxHeight: 320)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .accessibilityLabel(picture.title.isEmpty ? "Bild" : picture.title)
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

private struct InlineAttachmentImage: View {
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

    private static func load(_ reference: String) async throws -> CGImage {
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
