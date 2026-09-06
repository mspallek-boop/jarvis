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

        var messageAttachments: [MessageAttachment] {
            (attachments ?? []).compactMap { item in
                guard let kind = MessageAttachment.Kind(rawValue: item.kind) else { return nil }
                let attachment = MessageAttachment(kind: kind, url: item.url, title: item.title)
                return attachment.isDisplayable ? attachment : nil
            }
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

    struct VoicesResponse: Decodable {
        let provider: String
        let voices: [BridgeVoice]
        let selected: String
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

    func chatStreaming(message: String, conversation: String, clientRunID: String,
                       imagePath: String = "",
                       onFrame: (ChatFrame) -> Void) async throws -> ChatResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("chat/stream"))
        request.httpMethod = "POST"
        request.timeoutInterval = 420
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        var body = ["message": message, "conversation": conversation, "client_run_id": clientRunID]
        if !imagePath.isEmpty { body["image_path"] = imagePath }
        request.httpBody = try JSONEncoder().encode(body)
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
        var textBytes = 0
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard line.utf8.count < 800_000 else { throw ClientError.server("Antwort zu groß.") }
            let frame = try JSONDecoder().decode(ChatFrame.self, from: Data(line.utf8))
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
        let (data, response) = try await perform(request)
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

    private func perform(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
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
