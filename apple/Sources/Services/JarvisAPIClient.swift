import Foundation

struct JarvisAPIClient {
    struct Tool: Decodable {
        let name: String
        let preview: String?
    }

    struct Attachment: Decodable {
        let kind: String
        let url: String
        let title: String
    }

    struct ChatResponse: Decodable {
        let text: String
        let tools: [Tool]
        let run_id: String?
        let duration_ms: Int?
        let attachments: [Attachment]?

        enum CodingKeys: String, CodingKey { case text, tools, run_id, duration_ms, attachments }

        init(from decoder: Decoder) throws {
            let values = try decoder.container(keyedBy: CodingKeys.self)
            let extracted = InlineImageData.extract(from: try values.decode(String.self, forKey: .text))
            guard extracted.text.utf8.count < 1_000_000 else { throw ClientError.server("Antwort zu groß.") }
            text = extracted.text
            tools = try values.decode([Tool].self, forKey: .tools)
            run_id = try values.decodeIfPresent(String.self, forKey: .run_id)
            duration_ms = try values.decodeIfPresent(Int.self, forKey: .duration_ms)
            attachments = (try values.decodeIfPresent([Attachment].self, forKey: .attachments) ?? [])
                + extracted.attachments.map { Attachment(kind: $0.kind.rawValue, url: $0.url, title: $0.title) }
        }

        var messageAttachments: [MessageAttachment] {
            MessageAttachment.bounded((attachments ?? []).compactMap { item in
                guard let kind = MessageAttachment.Kind(rawValue: item.kind) else { return nil }
                return MessageAttachment(kind: kind, url: item.url, title: item.title)
            })
        }
    }

    struct ChatFrame: Decodable {
        let type: String
        let text: String?
        let phase: String?
        let tool: String?
        let response: ChatResponse?
        let error: String?
    }

    struct HealthResponse: Decodable {
        let ok: Bool
        let mac: String?
    }

    struct RunStatus: Decodable, Identifiable, Equatable {
        let client_run_id: String
        let phase: String
        let tool: String
        let conversation: String
        let seconds: Double

        var id: String { client_run_id }

        var phaseLabel: String {
            switch phase {
            case "queued": return "wartet"
            case "thinking": return "denkt nach"
            case "answering": return "antwortet"
            case "tool":
                let name = tool.lowercased()
                if name.contains("search") || name.contains("web") { return "Web-Suche" }
                return tool.isEmpty ? "arbeitet" : tool
            case "stopping": return "bricht ab"
            default: return "arbeitet"
            }
        }

        var elapsedLabel: String {
            let total = max(0, Int(seconds.rounded(.down)))
            return total >= 3600
                ? String(format: "%d:%02d:%02d", total / 3600, (total / 60) % 60, total % 60)
                : String(format: "%d:%02d", total / 60, total % 60)
        }
    }

    struct RunsResponse: Decodable {
        let runs: [RunStatus]
        let count: Int
    }

    /// A task that outlives the app: JARVIS standing in for the user in one
    /// chat until `until`. The bridge deliberately sends no phone number —
    /// a name and a time is all the interface has any use for.
    struct Standin: Decodable, Identifiable, Equatable {
        /// One line JARVIS wrote after answering: what it was about, not what
        /// was said. The messages themselves stay in WhatsApp.
        struct Note: Decodable, Equatable, Hashable {
            let at: Double
            let gist: String
            let urgent: Bool

            var time: Date { Date(timeIntervalSince1970: at) }
        }

        let id: String
        let name: String
        let until: Double
        let started: Double
        let announced: Bool
        let exchanges: Int
        let history: [Note]

        var endsAt: Date { Date(timeIntervalSince1970: until) }

        var startedAtLabel: String {
            Date(timeIntervalSince1970: started)
                .formatted(date: .omitted, time: .shortened)
        }
    }

    struct StandinsResponse: Decodable {
        let standins: [Standin]
        let count: Int
    }

    struct Notification: Decodable, Identifiable, Equatable {
        let id: Int
        let kind: String
        let title: String
        let text: String
        let at: Double

        var line: String {
            let subject = title.trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return [subject, detail].filter { !$0.isEmpty }.joined(separator: " ")
        }
    }

    struct NotificationsResponse: Decodable {
        let notifications: [Notification]
        let unread: Int
        let latest: Int
    }

    struct Activity: Decodable {
        let phase: String
        let tool: String

        var label: String {
            switch phase {
            case "queued": return "Auftrag wartet"
            case "answering": return "Ich formuliere die Antwort"
            case "stopping": return "Ich breche ab"
            case "tool":
                let name = tool.lowercased()
                if name.contains("search") { return "Ich recherchiere" }
                if name.contains("browser") || name.contains("web") { return "Ich lese im Web" }
                if name.contains("memory") { return "Ich prüfe meine Notizen" }
                return tool.isEmpty ? "Ich arbeite daran" : "Werkzeug: \(tool)"
            default: return "Ich denke nach"
            }
        }
    }

    struct FileItem: Decodable, Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let is_directory: Bool
        let size: Int64
        let modified: TimeInterval
    }

    struct FileListing: Decodable {
        let path: String
        let parent: String
        let items: [FileItem]
    }

    enum ClientError: LocalizedError {
        case invalidURL
        case insecurePublicURL
        case unauthorized
        case server(String)
        case emptyResponse
        case timedOut

        var errorDescription: String? {
            switch self {
            case .invalidURL: return "Die Server-Adresse ist ungültig."
            case .insecurePublicURL: return "Unverschlüsseltes HTTP ist nur im privaten Netz erlaubt."
            case .unauthorized: return "Der App-Token stimmt nicht."
            case .server(let message): return message
            case .emptyResponse: return "JARVIS hat leer geantwortet."
            case .timedOut: return "JARVIS antwortet nicht. Prüfe Tailscale und die Server-Adresse."
            }
        }
    }

    struct BridgeVoice: Decodable, Identifiable, Hashable {
        let id: String
        let name: String
        let accent: String
        let gender: String
        let description: String

        /// "Daniel · britisch · männlich" — the accent matters most when the
        /// voice has to speak German.
        var label: String {
            let german = ["british": "britisch", "american": "amerikanisch",
                          "australian": "australisch", "irish": "irisch",
                          "transatlantic": "transatlantisch", "indian": "indisch",
                          "swedish": "schwedisch", "german": "deutsch"]
            let parts = [name, german[accent.lowercased()] ?? accent].filter { !$0.isEmpty }
            return parts.joined(separator: " · ")
        }
    }

    /// One heading in the voice picker. The bridge groups them because the two
    /// are not peers: Piper is local, free and unlimited, while ElevenLabs is a
    /// monthly allowance this account empties in days — which is what made
    /// JARVIS mute in the first place.
    struct VoiceGroup: Decodable, Identifiable {
        let id: String
        let title: String
        let note: String
        let deprecated: Bool
        let voices: [BridgeVoice]
        let selected: String
        let error: String?
    }

    struct VoicesResponse: Decodable {
        let provider: String
        let voices: [BridgeVoice]
        let selected: String
        /// Absent when talking to a bridge from before the grouping existed.
        let groups: [VoiceGroup]?

        /// Grouped when the bridge offers it, otherwise the old flat list under
        /// one heading, so an older Mac still shows something usable.
        var displayGroups: [VoiceGroup] {
            if let groups, !groups.isEmpty { return groups }
            return [VoiceGroup(id: "legacy", title: "Stimmen", note: "", deprecated: false,
                               voices: voices, selected: selected, error: nil)]
        }
    }

    let baseURL: URL
    let token: String
    /// Chosen in Settings. Empty means the voice configured on the Mac.
    var voiceID: String = ""

    init(urlString: String, token: String, voiceID: String = "") throws {
        let normalized = urlString.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: normalized), url.host != nil else { throw ClientError.invalidURL }
        if url.scheme?.lowercased() == "http", !Self.isPrivateHost(url.host ?? "") {
            throw ClientError.insecurePublicURL
        }
        self.baseURL = url
        self.token = token
        self.voiceID = voiceID
    }

    func voices() async throws -> VoicesResponse {
        let data = try await request(path: "voices", method: "GET", body: Optional<String>.none, timeout: 25)
        return try JSONDecoder().decode(VoicesResponse.self, from: data)
    }

    func health() async throws -> HealthResponse {
        let data = try await request(path: "health", method: "GET", body: Optional<String>.none, timeout: 6)
        return try JSONDecoder().decode(HealthResponse.self, from: data)
    }

    func runs() async throws -> RunsResponse {
        let data = try await request(path: "runs", method: "GET", body: Optional<String>.none, timeout: 8)
        return try JSONDecoder().decode(RunsResponse.self, from: data)
    }

    func standins() async throws -> [Standin] {
        let data = try await request(path: "standins", method: "GET", body: Optional<String>.none, timeout: 8)
        return try JSONDecoder().decode(StandinsResponse.self, from: data).standins
    }

    func notifications(since: Int, unreadOnly: Bool = false) async throws -> NotificationsResponse {
        var components = URLComponents(url: baseURL.appendingPathComponent("notifications"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "since", value: String(max(0, since))),
            URLQueryItem(name: "unread", value: unreadOnly ? "1" : "0")
        ]
        let data = try await rawRequest(url: components.url!, method: "GET", timeout: 8)
        return try JSONDecoder().decode(NotificationsResponse.self, from: data)
    }

    func markNotificationsRead(through: Int) async throws {
        let _: Data = try await request(path: "notifications/read", method: "POST",
                                        body: ["through": through], timeout: 8)
    }

    func wake() async throws {
        let _: Data = try await request(path: "wake", method: "POST", body: ["wake": true], timeout: 100)
    }

    func activity(clientRunID: String) async throws -> Activity {
        var components = URLComponents(url: baseURL.appendingPathComponent("activity"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "client_run_id", value: clientRunID)]
        let data = try await rawRequest(url: components.url!, method: "GET", timeout: 6)
        return try JSONDecoder().decode(Activity.self, from: data)
    }

    func files(path: String?) async throws -> FileListing {
        var components = URLComponents(url: baseURL.appendingPathComponent("files"), resolvingAgainstBaseURL: false)!
        if let path { components.queryItems = [URLQueryItem(name: "path", value: path)] }
        let data = try await rawRequest(url: components.url!, method: "GET", timeout: 20)
        return try JSONDecoder().decode(FileListing.self, from: data)
    }

    func download(path: String, name: String) async throws -> URL {
        var components = URLComponents(url: baseURL.appendingPathComponent("files/download"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "path", value: path)]
        let data = try await rawRequest(url: components.url!, method: "GET", timeout: 120)
        let destination = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
            .appendingPathComponent(name)
        try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: destination, options: .atomic)
        return destination
    }

    func chat(message: String, conversation: String, clientRunID: String = UUID().uuidString,
              imagePath: String = "") async throws -> ChatResponse {
        struct Body: Encodable {
            let message: String; let conversation: String
            let client_run_id: String; let image_path: String
        }
        let data = try await request(path: "chat", method: "POST",
                                     body: Body(message: message, conversation: conversation,
                                                client_run_id: clientRunID, image_path: imagePath),
                                     timeout: 420)
        let response = try JSONDecoder().decode(ChatResponse.self, from: data)
        guard !response.text.isEmpty else { throw ClientError.emptyResponse }
        return response
    }

    func speechRequest(text: String) throws -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent("speech"))
        request.httpMethod = "POST"
        request.timeoutInterval = 90
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        // The bridge rejects a voice the account does not offer, so an empty
        // value is the safe default rather than a guess.
        request.httpBody = try JSONEncoder().encode(
            voiceID.isEmpty ? ["text": text] : ["text": text, "voice_id": voiceID])
        return request
    }

    @MainActor
    struct UploadResponse: Decodable {
        let path: String
        let name: String
    }

    /// Hands a pasted picture to the Mac. Only the returned path is ever sent
    /// back with a message; the bridge refuses any other path.
    func upload(imageData: Data) async throws -> UploadResponse {
        let body = ["data": imageData.base64EncodedString()]
        let data = try await request(path: "upload", method: "POST", body: body, timeout: 120)
        return try JSONDecoder().decode(UploadResponse.self, from: data)
    }

    /// `parallel` lets a turn start while another is still running, in a side
    /// lane the bridge opens. Without it the second turn waits for the first.
    func chatStreaming(message: String, conversation: String, clientRunID: String,
                       imagePath: String = "", parallel: Bool = false,
                       onFrame: (ChatFrame) -> Void) async throws -> ChatResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("chat/stream"))
        request.httpMethod = "POST"
        request.timeoutInterval = 420
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        var body: [String: Any] = ["message": message, "conversation": conversation,
                                   "client_run_id": clientRunID]
        if !imagePath.isEmpty { body["image_path"] = imagePath }
        if parallel { body["parallel"] = true }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw ClientError.emptyResponse }
        if http.statusCode == 404 || http.statusCode == 405 {
            // Older bridges reject this route before starting a turn. Never
            // retry after a stream has begun: tools might already have acted.
            return try await chat(message: message, conversation: conversation,
                                  clientRunID: clientRunID, imagePath: imagePath)
        }
        if http.statusCode == 401 { throw ClientError.unauthorized }
        guard http.statusCode == 200,
              http.value(forHTTPHeaderField: "Content-Type")?.contains("application/x-ndjson") == true else {
            throw ClientError.server("Gesprächsverbindung fehlgeschlagen (\(http.statusCode)).")
        }
        return try await Self.consumeChatStream(bytes, onFrame: onFrame)
    }

    static let maxChatFrameBytes = 16 * 1024 * 1024

    /// Limit the buffer before constructing a line, including an unterminated
    /// malicious frame. The same parser is exercised by the offline tests.
    static func consumeChatStream<Bytes: AsyncSequence>(_ bytes: Bytes,
        onFrame: (ChatFrame) -> Void) async throws -> ChatResponse where Bytes.Element == UInt8 {
        var textBytes = 0
        var line = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            if byte != 10 {
                guard line.count < maxChatFrameBytes else { throw ClientError.server("Antwort zu groß.") }
                line.append(byte)
                continue
            }
            if line.isEmpty { continue }
            let frame = try JSONDecoder().decode(ChatFrame.self, from: line)
            line.removeAll(keepingCapacity: true)
            switch frame.type {
            case "delta", "activity":
                textBytes += frame.text?.utf8.count ?? 0
                guard textBytes < 1_000_000 else { throw ClientError.server("Antwort zu groß.") }
                onFrame(frame)
            case "done":
                guard let answer = frame.response, !answer.text.isEmpty else { throw ClientError.emptyResponse }
                return answer
            case "error":
                throw ClientError.server(frame.error ?? "Antwort unterbrochen.")
            default: break
            }
        }
        throw ClientError.server("Antwort unterbrochen. Bitte erneut versuchen.")
    }

    func stop(clientRunID: String) async throws {
        let _: Data = try await request(path: "stop", method: "POST", body: ["client_run_id": clientRunID], timeout: 20)
    }

    private func request<Body: Encodable>(path: String, method: String, body: Body?, timeout: TimeInterval) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await perform(request, maxBytes: path == "chat" ? Self.maxChatFrameBytes : nil)
        guard let http = response as? HTTPURLResponse else { throw ClientError.server("Keine gültige Serverantwort.") }
        if http.statusCode == 401 { throw ClientError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            let decoded = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let message = decoded?["error"] as? String ?? "Serverfehler \(http.statusCode)"
            throw ClientError.server(message)
        }
        return data
    }

    private func rawRequest(url: URL, method: String, timeout: TimeInterval) async throws -> Data {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await perform(request)
        guard let http = response as? HTTPURLResponse else { throw ClientError.server("Keine gültige Serverantwort.") }
        if http.statusCode == 401 { throw ClientError.unauthorized }
        guard (200..<300).contains(http.statusCode) else {
            let decoded = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw ClientError.server(decoded?["error"] as? String ?? "Serverfehler \(http.statusCode)")
        }
        return data
    }

    private func perform(_ request: URLRequest, maxBytes: Int? = nil) async throws -> (Data, URLResponse) {
        do {
            if let maxBytes {
                let (bytes, response) = try await URLSession.shared.bytes(for: request)
                guard response.expectedContentLength <= maxBytes else { throw ClientError.server("Antwort zu groß.") }
                var data = Data()
                for try await byte in bytes {
                    try Task.checkCancellation()
                    guard data.count < maxBytes else { throw ClientError.server("Antwort zu groß.") }
                    data.append(byte)
                }
                return (data, response)
            }
            return try await URLSession.shared.data(for: request)
        } catch let error as URLError where error.code == .timedOut {
            throw ClientError.timedOut
        }
    }

    private static func isPrivateHost(_ host: String) -> Bool {
        let value = host.lowercased()
        if !value.contains(".") { return true }
        if value == "localhost" || value.hasSuffix(".local") || value.hasSuffix(".ts.net") { return true }
        if value.hasPrefix("10.") || value.hasPrefix("192.168.") || value.hasPrefix("127.") { return true }
        if value.hasPrefix("100.") {
            let parts = value.split(separator: ".").compactMap { Int($0) }
            return parts.count == 4 && (64...127).contains(parts[1])
        }
        if value.hasPrefix("172.") {
            let parts = value.split(separator: ".").compactMap { Int($0) }
            return parts.count == 4 && (16...31).contains(parts[1])
        }
        return value == "::1" || value.hasPrefix("fe80:") || value.hasPrefix("fc") || value.hasPrefix("fd")
    }
}
