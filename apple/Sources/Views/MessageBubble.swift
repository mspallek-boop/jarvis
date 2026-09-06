import SwiftUI

struct MessageBubble: View {
    let message: ChatMessage

    @EnvironmentObject private var model: AppModel

    private var ink: Color {
        model.backgroundChoice.foregroundColor
    }

    var body: some View {
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


/// Pictures, clips and the pages an answer came from, shown under it.
struct AttachmentStrip: View {
    let attachments: [MessageAttachment]
    let ink: Color

    @EnvironmentObject private var model: AppModel

    private var pictures: [MessageAttachment] { attachments.filter { $0.kind == .image } }
    private var links: [MessageAttachment] { attachments.filter { $0.kind != .image } }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(pictures) { picture in
                AsyncImage(url: URL(string: picture.url)) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().scaledToFit()
                    case .failure:
                        // Say the picture did not load rather than leaving a hole.
                        Label("Bild nicht ladbar", systemImage: "photo")
                            .font(model.appFont(.caption2))
                            .foregroundStyle(ink.opacity(0.5))
                            .padding(.vertical, 10)
                    default:
                        ProgressView().tint(ink).frame(height: 60)
                    }
                }
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
