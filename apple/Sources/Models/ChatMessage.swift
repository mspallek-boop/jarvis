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

    /// Only http(s) is ever rendered: a file: or data: URL from an answer would
    /// reach into the device or embed arbitrary bytes.
    var isDisplayable: Bool {
        guard let parsed = URL(string: url), let scheme = parsed.scheme?.lowercased() else { return false }
        return scheme == "https" || scheme == "http"
    }

    var host: String {
        (URL(string: url)?.host ?? "").replacingOccurrences(of: "www.", with: "")
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
        text = try values.decode(String.self, forKey: .text)
        timestamp = try values.decode(Date.self, forKey: .timestamp)
        tools = try values.decodeIfPresent([String].self, forKey: .tools) ?? []
        attachments = try values.decodeIfPresent([MessageAttachment].self, forKey: .attachments) ?? []
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
