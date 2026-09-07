import Foundation

/// Something JARVIS referred to and the app can show: a picture, a clip, or
/// the page an answer came from.
struct MessageAttachment: Identifiable, Codable, Equatable, Hashable {
    enum Kind: String, Codable {
        case image, video, source
    }

    var id: String { url }
    let kind: Kind
    let url: String
    let title: String

    /// Local paths never reach the device filesystem. The bridge supplies
    /// bounded raster bytes, including when the device is an iPhone.
    var isDisplayable: Bool {
        if kind == .image, InlineImageData.decode(url) != nil { return true }
        guard let parsed = URL(string: url), let scheme = parsed.scheme?.lowercased() else { return false }
        return scheme == "https" || scheme == "http"
    }

    var host: String {
        (URL(string: url)?.host ?? "").replacingOccurrences(of: "www.", with: "")
    }

    static func bounded(_ attachments: [MessageAttachment]) -> [MessageAttachment] {
        var total = 0
        var seen = Set<String>()
        return attachments.compactMap { attachment in
            guard seen.count < 12, !seen.contains(attachment.url), attachment.isDisplayable else { return nil }
            if attachment.url.hasPrefix("data:"), let data = InlineImageData.decode(attachment.url) {
                guard total + data.count <= InlineImageData.maxTotalBytes else { return nil }
                total += data.count
            }
            seen.insert(attachment.url)
            return attachment
        }
    }
}

enum InlineImageData {
    static let maxBytes = 5 * 1024 * 1024
    static let maxTotalBytes = 10 * 1024 * 1024
    static let mimeTypes = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"]

    static func decode(_ url: String) -> Data? {
        guard url.hasPrefix("data:"), url.utf8.count <= 4 * ((maxBytes + 2) / 3) + 40,
              let comma = url.firstIndex(of: ","),
              mimeTypes.contains(where: { url[..<comma] == "data:\($0);base64" }),
              let data = Data(base64Encoded: String(url[url.index(after: comma)...])),
              !data.isEmpty, data.count <= maxBytes else { return nil }
        return data
    }

    /// Compatibility with bridges that pass Hermes' Markdown data URLs through
    /// in text. Never interpret file URLs or MEDIA paths on the Apple device.
    static func extract(from text: String) -> (text: String, attachments: [MessageAttachment]) {
        let pattern = #"!\[([^\]\n]{0,120})\]\((data:[^\s)]*)\)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return (text, []) }
        var clean = text
        var attachments: [MessageAttachment] = []
        var seen = Set<String>()
        var total = 0
        let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
        var replacements: [(NSRange, String)] = []
        for match in matches {
            guard let urlRange = Range(match.range(at: 2), in: text),
                  let titleRange = Range(match.range(at: 1), in: text) else { continue }
            let url = String(text[urlRange])
            var label = "[Bild nicht verfügbar]"
            if let data = decode(url) {
                if seen.contains(url) { label = "[Bild]" }
                else if attachments.count < 12, total + data.count <= maxTotalBytes {
                    seen.insert(url)
                    total += data.count
                    attachments.append(MessageAttachment(kind: .image, url: url, title: String(text[titleRange])))
                    label = "[Bild]"
                }
            }
            replacements.append((match.range, label))
        }
        for (range, label) in replacements.reversed() {
            if let range = Range(range, in: clean) { clean.replaceSubrange(range, with: label) }
        }
        return (clean, attachments)
    }
}

struct ChatMessage: Identifiable, Codable, Equatable {
    enum Role: String, Codable {
        case user
        case jarvis
        case system
    }

    let id: UUID
    let role: Role
    let text: String
    let timestamp: Date
    var tools: [String]
    var attachments: [MessageAttachment]

    init(id: UUID = UUID(), role: Role, text: String, timestamp: Date = Date(),
         tools: [String] = [], attachments: [MessageAttachment] = []) {
        self.id = id
        self.role = role
        self.text = text
        self.timestamp = timestamp
        self.tools = tools
        self.attachments = attachments
    }

    // Archives written before attachments existed must still decode.
    enum CodingKeys: String, CodingKey {
        case id, role, text, timestamp, tools, attachments
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(UUID.self, forKey: .id)
        role = try values.decode(Role.self, forKey: .role)
        let rawText = try values.decode(String.self, forKey: .text)
        let extracted = role == .jarvis ? InlineImageData.extract(from: rawText) : (text: rawText, attachments: [])
        text = extracted.text
        timestamp = try values.decode(Date.self, forKey: .timestamp)
        tools = try values.decodeIfPresent([String].self, forKey: .tools) ?? []
        attachments = MessageAttachment.bounded(
            (try values.decodeIfPresent([MessageAttachment].self, forKey: .attachments) ?? []) + extracted.attachments)
    }
}

struct ChatConversation: Identifiable, Codable, Equatable {
    let id: String
    var title: String
    var messages: [ChatMessage]
    var updatedAt: Date
}

enum ChatHistoryStore {
    private static let fileName = "chat-history-v1.json"

    static func load() -> [ChatConversation] {
        guard let fileURL, let data = try? Data(contentsOf: fileURL) else { return [] }
        return (try? JSONDecoder().decode([ChatConversation].self, from: data)) ?? []
    }

    static func save(_ conversations: [ChatConversation]) {
        guard let fileURL, let data = try? JSONEncoder().encode(conversations) else { return }
        do {
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } catch {
            // Chat remains usable even when the local archive cannot be written.
        }
    }

    private static var fileURL: URL? {
        guard let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            return nil
        }
        let bundleID = Bundle.main.bundleIdentifier ?? "at.marlon.jarvis"
        return root.appendingPathComponent(bundleID, isDirectory: true).appendingPathComponent(fileName)
    }
}
