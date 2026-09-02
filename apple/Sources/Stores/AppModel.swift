import Combine
import Foundation
import SwiftUI

enum AppTheme: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "System"
        case .light: return "Hell"
        case .dark: return "Dunkel"
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

enum AppBackground: String, CaseIterable, Identifiable {
    case black
    case white
    case blue
    case green
    case orange
    case red
    case purple

    var id: String { rawValue }

    var label: String {
        switch self {
        case .black: return "Schwarz"
        case .white: return "Weiß"
        case .blue: return "Blau"
        case .green: return "Grün"
        case .orange: return "Orange"
        case .red: return "Rot"
        case .purple: return "Violett"
        }
    }

    var color: Color {
        switch self {
        case .black: return .black
        case .white: return .white
        case .blue: return .blue
        case .green: return .green
        case .orange: return .orange
        case .red: return .red
        case .purple: return .purple
        }
    }

    var foregroundColor: Color {
        switch self {
        case .white, .green, .orange:
            return .black
        case .black, .blue, .red, .purple:
            return .white
        }
    }
}

enum AppFontFamily: String, CaseIterable, Identifiable {
    case system
    case rounded
    case serif
    case monospaced
    case avenirNext
    case baskerville
    case charter
    case courierNew
    case futura
    case georgia
    case gillSans
    case helveticaNeue
    case helveticaBlock
    case hoeflerText
    case menlo
    case optima
    case palatino
    case timesNewRoman
    case trebuchetMS
    case verdana

    var id: String { rawValue }

    var label: String {
        switch self {
        case .system: return "System"
        case .rounded: return "System Rounded"
        case .serif: return "New York"
        case .monospaced: return "SF Mono"
        case .avenirNext: return "Avenir Next"
        case .baskerville: return "Baskerville"
        case .charter: return "Charter"
        case .courierNew: return "Courier New"
        case .futura: return "Futura"
        case .georgia: return "Georgia"
        case .gillSans: return "Gill Sans"
        case .helveticaNeue: return "Helvetica Neue"
        case .helveticaBlock: return "Helvetica Block"
        case .hoeflerText: return "Hoefler Text"
        case .menlo: return "Menlo"
        case .optima: return "Optima"
        case .palatino: return "Palatino"
        case .timesNewRoman: return "Times New Roman"
        case .trebuchetMS: return "Trebuchet MS"
        case .verdana: return "Verdana"
        }
    }

    fileprivate var customName: String? {
        switch self {
        case .system, .rounded, .serif, .monospaced: return nil
        case .avenirNext: return "Avenir Next"
        case .baskerville: return "Baskerville"
        case .charter: return "Charter"
        case .courierNew: return "Courier New"
        case .futura: return "Futura"
        case .georgia: return "Georgia"
        case .gillSans: return "Gill Sans"
        case .helveticaNeue: return "Helvetica Neue"
        case .helveticaBlock: return "HelveticaNeue-CondensedBlack"
        case .hoeflerText: return "Hoefler Text"
        case .menlo: return "Menlo"
        case .optima: return "Optima"
        case .palatino: return "Palatino"
        case .timesNewRoman: return "Times New Roman"
        case .trebuchetMS: return "Trebuchet MS"
        case .verdana: return "Verdana"
        }
    }

    fileprivate var design: Font.Design {
        switch self {
        case .rounded: return .rounded
        case .serif: return .serif
        case .monospaced: return .monospaced
        default: return .default
        }
    }

    func previewFont(size: CGFloat) -> Font {
        if let customName {
            return .custom(customName, size: size)
        }
        return .system(size: size, design: design)
    }
}

@MainActor
final class AppModel: ObservableObject {
    static let defaultServerURL = "http://macbook-air-von-marlon.tailfb3c35.ts.net:8770"
    private static let maximumMessageCount = 250

    enum ConnectionState: Equatable {
        case unchecked
        case checking
        case online
        case sleeping
        case offline(String)

        var label: String {
            switch self {
            case .unchecked: return "Nicht verbunden"
            case .checking: return "Prüfe Verbindung"
            case .online: return "Hermes online"
            case .sleeping: return "Relay online · Mac schläft"
            case .offline: return "Offline"
            }
        }
    }

    @Published var messages: [ChatMessage] = [
        ChatMessage(role: .jarvis, text: "System bereit. Womit darf ich helfen?")
    ]
    @Published var input = ""
    @Published var isWorking = false
    @Published var connection: ConnectionState = .unchecked
    @Published var showingSettings = false
    @Published var serverURL: String
    @Published var token: String
    @Published var speaksReplies: Bool
    @Published var conversation: String
    @Published var theme: AppTheme
    @Published var backgroundChoice: AppBackground
    @Published var fontFamily: AppFontFamily
    @Published var fontScale: Double
    @Published var lastError: String?
    @Published var files: [JarvisAPIClient.FileItem] = []
    @Published var filePath: String?
    @Published var fileParent: String?
    @Published var isLoadingFiles = false
    @Published var downloadedFile: URL?
    let speech = SpeechController()
    private var speechObserver: AnyCancellable?
#if os(iOS)
    private var watchConnectivityController: WatchConnectivityController?
#endif

    init() {
        let storedURL = UserDefaults.standard.string(forKey: "serverURL")
        if Self.shouldMigrateServerURL(storedURL) {
            serverURL = Self.defaultServerURL
            UserDefaults.standard.set(Self.defaultServerURL, forKey: "serverURL")
        } else {
            serverURL = storedURL ?? Self.defaultServerURL
        }
        token = KeychainStore.loadToken()
        speaksReplies = UserDefaults.standard.object(forKey: "speaksReplies") as? Bool ?? true
        conversation = UserDefaults.standard.string(forKey: "conversation") ?? "jarvis-apple"
        theme = AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearanceTheme") ?? "") ?? .system
        let storedBackground = UserDefaults.standard.string(forKey: "appearanceBackground")
            ?? UserDefaults.standard.string(forKey: "appearanceAccent")
        backgroundChoice = AppBackground(rawValue: storedBackground ?? "") ?? .black
        fontFamily = AppFontFamily(rawValue: UserDefaults.standard.string(forKey: "appearanceFont") ?? "") ?? .system
        let savedScale = UserDefaults.standard.object(forKey: "appearanceFontScale") as? Double ?? 1
        fontScale = min(max(savedScale, 0.8), 1.4)
        speechObserver = speech.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
#if os(iOS)
        let watchController = WatchConnectivityController()
        watchController.messageHandler = { [weak self] text in
            guard let self else { return "JARVIS ist gerade nicht verfügbar." }
            return await self.sendFromWatch(text)
        }
        watchConnectivityController = watchController
#endif
    }

    private static func shouldMigrateServerURL(_ storedURL: String?) -> Bool {
        guard let storedURL else { return true }
        let normalized = storedURL
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            .lowercased()

        // :8766 must migrate too. The bridge briefly defaulted to that port,
        // where it collided with the voice server's tls_ports [443, 8766] —
        // and jarvis-stop.sh kills 8766, so stopping voice killed the bridge.
        // The bridge now lives on 8770; an install still holding 8766 points at
        // the voice server's TLS port and fails in a confusing way.
        return normalized.contains("jarvis.local")
            || normalized.hasSuffix(":8765")
            || normalized.hasSuffix(":8766")
    }

    /// Pull the bare token out of whatever was pasted into the token field.
    ///
    /// A paste from `~/.hermes/.env` usually carries more than the token: the
    /// whole `JARVIS_APP_TOKEN=…` line, or several lines at once. Trimming only
    /// the ends leaves the interior intact, so the app stored the mess and the
    /// bridge answered 401 with no hint as to why. A token never contains
    /// whitespace, so this is unambiguous to undo.
    static func sanitizeToken(_ raw: String) -> String {
        let parts = raw
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }

        // A full .env paste: pick the line that actually holds the app token.
        if let line = parts.first(where: { $0.hasPrefix("JARVIS_APP_TOKEN=") }) {
            return String(line.dropFirst("JARVIS_APP_TOKEN=".count))
        }
        guard let single = parts.first, parts.count == 1 else {
            // Several fragments and none is the app-token line — refuse to
            // guess. An empty token surfaces as a clear "token is wrong"
            // rather than a silent, subtly corrupted value.
            return parts.count == 1 ? parts[0] : ""
        }
        // A single "SOME_KEY=value" fragment: keep the value.
        if let eq = single.firstIndex(of: "="),
           single[single.startIndex..<eq].allSatisfy({ $0.isUppercase || $0 == "_" }),
           single.index(after: eq) < single.endIndex {
            return String(single[single.index(after: eq)...])
        }
        return single
    }

    func saveSettings() {
        serverURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        token = Self.sanitizeToken(token)
        conversation = conversation.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(serverURL, forKey: "serverURL")
        UserDefaults.standard.set(speaksReplies, forKey: "speaksReplies")
        UserDefaults.standard.set(conversation, forKey: "conversation")
        KeychainStore.save(token: token)
        saveAppearanceSettings()
    }

    func saveAppearanceSettings() {
        UserDefaults.standard.set(theme.rawValue, forKey: "appearanceTheme")
        UserDefaults.standard.set(backgroundChoice.rawValue, forKey: "appearanceBackground")
        UserDefaults.standard.set(fontFamily.rawValue, forKey: "appearanceFont")
        UserDefaults.standard.set(fontScale, forKey: "appearanceFontScale")
    }

    func resetAppearanceSettings() {
        theme = .system
        backgroundChoice = .black
        fontFamily = .system
        fontScale = 1
        saveAppearanceSettings()
    }

    func appFont(_ style: Font.TextStyle, weight: Font.Weight = .regular) -> Font {
        let size = Self.baseFontSize(for: style) * fontScale
        if let customName = fontFamily.customName {
            let font = Font.custom(customName, size: size, relativeTo: style)
            // This face already contains its heavy weight. Applying another
            // SwiftUI weight can make it fall back to a different Helvetica.
            return fontFamily == .helveticaBlock ? font : font.weight(weight)
        }
        return .system(size: size, weight: weight, design: fontFamily.design)
    }

    private static func baseFontSize(for style: Font.TextStyle) -> CGFloat {
        switch style {
        case .largeTitle: return 34
        case .title: return 28
        case .title2: return 22
        case .title3: return 20
        case .headline: return 17
        case .body: return 17
        case .callout: return 16
        case .subheadline: return 15
        case .footnote: return 13
        case .caption: return 12
        case .caption2: return 11
        @unknown default: return 17
        }
    }

    func checkConnection() async {
        connection = .checking
        do {
            let client = try JarvisAPIClient(urlString: serverURL, token: token)
            let health = try await client.health()
            if health.mac == "sleeping_or_off" {
                connection = .sleeping
            } else {
                connection = health.ok ? .online : .offline("Hermes meldet einen Fehler")
            }
        } catch {
            connection = .offline(error.localizedDescription)
        }
    }

    func wakeMac() async {
        do {
            let client = try JarvisAPIClient(urlString: serverURL, token: token)
            try await client.wake()
            connection = .checking
            try? await Task.sleep(for: .seconds(4))
            await checkConnection()
        } catch {
            lastError = error.localizedDescription
            connection = .offline(error.localizedDescription)
        }
    }

    func loadFiles(path: String? = nil) async {
        isLoadingFiles = true
        defer { isLoadingFiles = false }
        do {
            let client = try JarvisAPIClient(urlString: serverURL, token: token)
            let listing = try await client.files(path: path)
            files = listing.items
            filePath = listing.path
            fileParent = listing.parent
        } catch {
            lastError = error.localizedDescription
        }
    }

    func download(_ item: JarvisAPIClient.FileItem) async {
        do {
            let client = try JarvisAPIClient(urlString: serverURL, token: token)
            downloadedFile = try await client.download(path: item.path, name: item.name)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func send(_ explicitText: String? = nil) async {
        let text = (explicitText ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isWorking else { return }
        input = ""
        lastError = nil
        appendMessage(ChatMessage(role: .user, text: text))
        isWorking = true
        defer { isWorking = false }
        do {
            let client = try JarvisAPIClient(urlString: serverURL, token: token)
            let response = try await client.chat(message: text, conversation: conversation)
            let names = response.tools.map(\.name)
            appendMessage(ChatMessage(role: .jarvis, text: response.text, tools: names))
            connection = .online
            if speaksReplies { speech.speak(response.text) }
        } catch {
            lastError = error.localizedDescription
            connection = .offline(error.localizedDescription)
            appendMessage(ChatMessage(role: .system, text: error.localizedDescription))
        }
    }

    func toggleListening() async {
        if speech.isListening {
            if let text = speech.stop() { await send(text) }
        } else {
            await speech.start()
        }
    }

#if os(iOS)
    private func sendFromWatch(_ text: String) async -> String {
        let cleanText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanText.isEmpty else { return "Ich habe nichts verstanden." }

        appendMessage(ChatMessage(role: .user, text: cleanText))
        do {
            let client = try JarvisAPIClient(urlString: serverURL, token: token)
            let response = try await client.chat(message: cleanText, conversation: conversation)
            appendMessage(ChatMessage(role: .jarvis, text: response.text, tools: response.tools.map(\.name)))
            connection = .online
            return response.text
        } catch {
            connection = .offline(error.localizedDescription)
            appendMessage(ChatMessage(role: .system, text: error.localizedDescription))
            return error.localizedDescription
        }
    }
#endif

    private func appendMessage(_ message: ChatMessage) {
        messages.append(message)
        let overflow = messages.count - Self.maximumMessageCount
        if overflow > 0 {
            messages.removeFirst(overflow)
        }
    }
}
