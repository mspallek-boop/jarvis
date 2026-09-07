import Combine
import Foundation
import UniformTypeIdentifiers
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
    static let defaultServerURL = "https://macbook-air-von-marlon.tailfb3c35.ts.net:8443"
    private static let maximumMessageCount = 250
    private static let maximumConversationCount = 30

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
    @Published private(set) var conversations: [ChatConversation] = []
    @Published var input = ""
    @Published var isWorking = false
    @Published private(set) var activityLabel = "Ich denke nach"
    @Published private(set) var runs: [JarvisAPIClient.RunStatus] = []
    @Published private(set) var notificationBanner: String?
    @Published private(set) var liveResponse = ""
    @Published var connection: ConnectionState = .unchecked
    @Published var showingSettings = false
    @Published var serverURL: String
    @Published var token: String
    @Published var speaksReplies: Bool {
        didSet {
            UserDefaults.standard.set(speaksReplies, forKey: "speaksReplies")
            if !speaksReplies {
                speech.stopSpeaking()
                Task { await resumeVoice() }
            }
        }
    }
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
    @Published private(set) var voiceModeEnabled = true
    private var voiceForeground = false
    /// Voices the Mac's speech provider offers. Fetched through the bridge so
    /// the provider API key never reaches the app.
    @Published private(set) var availableBridgeVoices: [JarvisAPIClient.BridgeVoice] = []
    @Published private(set) var voiceListError: String?
    @Published var selectedBridgeVoice: String = UserDefaults.standard.string(forKey: "selectedBridgeVoice") ?? "" {
        didSet { UserDefaults.standard.set(selectedBridgeVoice, forKey: "selectedBridgeVoice") }
    }

    /// A pasted picture, waiting to go out with the next message.
    @Published private(set) var pendingImagePath = ""
    @Published private(set) var pendingImageData: Data?
    @Published private(set) var isUploadingImage = false

    /// Accepts a picture from the clipboard and parks it on the Mac.
    func attachImage(_ data: Data) async {
        guard !data.isEmpty, !isUploadingImage else { return }
        isUploadingImage = true
        defer { isUploadingImage = false }
        do {
            let stored = try await makeClient().upload(imageData: data)
            pendingImagePath = stored.path
            pendingImageData = data
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    /// Nothing to send without either words or a picture.
    var cannotSend: Bool {
        (input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && pendingImagePath.isEmpty)
            || isWorking || isUploadingImage
    }

    /// Pulls the first usable picture out of a paste and uploads it.
    func attachPastedImage(from providers: [NSItemProvider]) async {
        for provider in providers {
            for type in [UTType.png, .jpeg, .heic, .gif, .tiff, .image]
            where provider.hasItemConformingToTypeIdentifier(type.identifier) {
                guard let raw = await Self.loadData(from: provider, type: type) else { continue }
                // Normalise first: a macOS screenshot lands on the clipboard as
                // TIFF, which the bridge would refuse.
                guard let png = PlatformImage.pngData(from: raw) else { continue }
                await attachImage(png)
                return
            }
        }
        lastError = "In der Zwischenablage war kein Bild."
    }

    /// NSItemProvider's callback API, bridged once instead of at each call.
    private static func loadData(from provider: NSItemProvider, type: UTType) async -> Data? {
        await withCheckedContinuation { continuation in
            provider.loadDataRepresentation(forTypeIdentifier: type.identifier) { data, _ in
                continuation.resume(returning: data)
            }
        }
    }

    #if os(iOS)
    func attachClipboardImage() async {
        guard let png = PlatformImage.clipboardPNG() else {
            lastError = "In der Zwischenablage war kein Bild."
            return
        }
        await attachImage(png)
    }
    #endif

    func discardPendingImage() {
        pendingImagePath = ""
        pendingImageData = nil
    }

    /// One place that knows the chosen voice, so every request carries it.
    func makeClient() throws -> JarvisAPIClient {
        try JarvisAPIClient(urlString: serverURL, token: token, voiceID: selectedBridgeVoice)
    }

    func loadVoices() async {
        guard !token.isEmpty else { return }
        do {
            let response = try await makeClient().voices()
            availableBridgeVoices = response.voices
            voiceListError = response.voices.isEmpty
                ? "Der Mac nutzt gerade keine Anbieter-Stimme."
                : nil
            // A voice removed on the Mac must not stay selected here.
            if !selectedBridgeVoice.isEmpty,
               !response.voices.contains(where: { $0.id == selectedBridgeVoice }) {
                selectedBridgeVoice = ""
            }
        } catch {
            availableBridgeVoices = []
            voiceListError = error.localizedDescription
        }
    }
    private var activeRunID: String?
    private var chatTask: Task<JarvisAPIClient.ChatResponse, Error>?
    private var statusPollTask: Task<Void, Never>?
    private var bannerTask: Task<Void, Never>?
    private var notificationCursor: Int {
        get { UserDefaults.standard.integer(forKey: "notificationCursor") }
        set { UserDefaults.standard.set(newValue, forKey: "notificationCursor") }
    }
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
        // Every full app launch starts in a fresh conversation. The archived
        // conversations are restored below and remain selectable in history.
        conversation = Self.makeConversationID()
        theme = AppTheme(rawValue: UserDefaults.standard.string(forKey: "appearanceTheme") ?? "") ?? .system
        let storedBackground = UserDefaults.standard.string(forKey: "appearanceBackground")
            ?? UserDefaults.standard.string(forKey: "appearanceAccent")
        backgroundChoice = AppBackground(rawValue: storedBackground ?? "") ?? .black
        fontFamily = AppFontFamily(rawValue: UserDefaults.standard.string(forKey: "appearanceFont") ?? "") ?? .system
        let savedScale = UserDefaults.standard.object(forKey: "appearanceFontScale") as? Double ?? 1
        fontScale = min(max(savedScale, 0.8), 1.4)
        restoreChatHistory()
        speech.onUtterance = { [weak self] text in
            guard let self, self.voiceModeEnabled, self.voiceForeground else { return }
            Task {
                // Barge-in delivers speech while the previous turn still runs.
                // send() ignores input while isWorking, so end that turn first.
                if self.isWorking { await self.cancelActiveRun(announcing: false) }
                await self.send(text)
            }
        }
        // The countdown must not end the microphone mid-turn: while a run is
        // going, silence means the user is listening, not gone.
        speech.shouldKeepListening = { [weak self] in self?.isWorking ?? false }
        speech.onSpeechFinished = { [weak self] in
            Task { await self?.resumeVoice() }
        }
        speechObserver = speech.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
#if os(iOS)
        let watchController = WatchConnectivityController()
        watchController.messageHandler = { [weak self] text, requestID in
            guard let self else { return "JARVIS ist gerade nicht verfügbar." }
            return await self.sendFromWatch(text, requestID: requestID)
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
            || normalized == "http://macbook-air-von-marlon.tailfb3c35.ts.net:8770"
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
        UserDefaults.standard.set(serverURL, forKey: "serverURL")
        UserDefaults.standard.set(speaksReplies, forKey: "speaksReplies")
        UserDefaults.standard.set(conversation, forKey: "conversation")
        KeychainStore.save(token: token)
        saveAppearanceSettings()
    }

    func startNewConversation() {
        guard !isWorking else { return }
        if speech.isListening { _ = speech.stop() }
        input = ""
        lastError = nil

        let newConversation = ChatConversation(
            id: Self.makeConversationID(),
            title: "Neuer Chat",
            messages: [Self.makeWelcomeMessage()],
            updatedAt: Date()
        )
        conversation = newConversation.id
        messages = newConversation.messages
        conversations.insert(newConversation, at: 0)
        storeChatHistory()
    }

    func selectConversation(_ id: String) {
        guard !isWorking, id != conversation,
              let selected = conversations.first(where: { $0.id == id }) else { return }
        if speech.isListening { _ = speech.stop() }
        input = ""
        lastError = nil
        conversation = selected.id
        messages = selected.messages.isEmpty ? [Self.makeWelcomeMessage()] : selected.messages
        UserDefaults.standard.set(conversation, forKey: "conversation")
    }

    func deleteConversation(_ id: String) {
        guard !isWorking else { return }
        conversations.removeAll { $0.id == id }

        if id == conversation {
            if let next = conversations.sorted(by: { $0.updatedAt > $1.updatedAt }).first {
                conversation = next.id
                messages = next.messages.isEmpty ? [Self.makeWelcomeMessage()] : next.messages
                UserDefaults.standard.set(conversation, forKey: "conversation")
            } else {
                startNewConversation()
                return
            }
        }
        storeChatHistory()
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
            let client = try makeClient()
            let health = try await client.health()
            if health.mac == "sleeping_or_off" {
                connection = .sleeping
            } else {
                connection = health.ok ? .online : .offline("Hermes meldet einen Fehler")
            }
            await refreshStatus()
        } catch {
            connection = .offline(error.localizedDescription)
        }
    }

    private func refreshStatus() async {
        guard !token.isEmpty else { return }
        do {
            let client = try makeClient()
            runs = try await client.runs().runs
        } catch {
            // The status board is supplementary; a temporary timeout must not
            // turn a healthy chat connection into an error banner.
        }
        do {
            let client = try makeClient()
            let response = try await client.notifications(since: notificationCursor)
            guard !response.notifications.isEmpty else { return }
            let newItems = response.notifications
            for item in newItems {
                appendMessage(ChatMessage(role: .system, text: item.line))
            }
            notificationBanner = newItems.count == 1
                ? newItems[0].line
                : "\(newItems.count) Benachrichtigungen"
            bannerTask?.cancel()
            bannerTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(6))
                guard !Task.isCancelled else { return }
                self?.notificationBanner = nil
            }
            if speaksReplies, !isWorking, !speech.isSpeaking, voiceForeground {
                speech.speak(newItems.count == 1 ? newItems[0].line : "Du hast \(newItems.count) neue Benachrichtigungen.")
            }
            do {
                try await client.markNotificationsRead(through: response.latest)
                notificationCursor = max(notificationCursor, response.latest)
            } catch {
                // Keep the cursor unchanged so an unread notification is not
                // lost if the acknowledgement request briefly fails.
            }
        } catch {
            // Notifications are best-effort and will be retried on the next poll.
        }
    }

    func dismissNotificationBanner() {
        notificationBanner = nil
        bannerTask?.cancel()
    }

    private func startStatusPolling() {
        statusPollTask?.cancel()
        statusPollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(18))
                guard !Task.isCancelled, let self, self.voiceForeground else { return }
                await self.refreshStatus()
            }
        }
    }

    func wakeMac() async {
        do {
            let client = try makeClient()
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
            let client = try makeClient()
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
            let client = try makeClient()
            downloadedFile = try await client.download(path: item.path, name: item.name)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func setVoiceForeground(_ active: Bool) async {
        voiceForeground = active
        if active {
            startStatusPolling()
            await resumeVoice()
        } else {
            statusPollTask?.cancel()
            statusPollTask = nil
            speech.suspend()
        }
    }

    func setTyping(_ typing: Bool) async {
        voiceModeEnabled = !typing
        if typing { speech.suspend() } else { await resumeVoice() }
    }

    private func resumeVoice() async {
        guard voiceModeEnabled, voiceForeground, !showingSettings, !token.isEmpty else { return }
        if speech.interruptsBySpeaking {
            // Continuous listening: no waiting for the turn to finish. This
            // path must always end in a live microphone, so it never returns
            // early on a device without echo cancellation.
            await speech.listenThrough()
            return
        }
        guard !isWorking, !speech.isSpeaking else { return }
        await speech.start()
    }

    func send(_ explicitText: String? = nil) async {
        let text = (explicitText ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard (!text.isEmpty || !pendingImagePath.isEmpty), !isWorking, !isUploadingImage else { return }
        let message = text.isEmpty ? "Was ist auf diesem Bild zu sehen?" : text
        if speech.interruptsBySpeaking && voiceModeEnabled && voiceForeground {
            // Keep hearing the user through thinking and speaking alike.
            await speech.listenThrough()
        } else {
            speech.suspend()
        }
        input = ""
        lastError = nil
        appendMessage(ChatMessage(role: .user, text: message))
        // The picture belongs to this turn only, so it is taken now and the
        // composer cleared: a stale one must not ride along with the next
        // question.
        let attachedImage = pendingImagePath
        discardPendingImage()
        isWorking = true
        let id = UUID().uuidString
        activeRunID = id
        activityLabel = "Ich denke nach"
        liveResponse = ""
        var sentences = SpeechSentenceBuffer()
        var announcedTool = false
        let shouldSpeak = speaksReplies && voiceForeground
        do {
            let client = try makeClient()
            if shouldSpeak { speech.beginStream(client: client) }
            let conversationID = conversation
            let pending = Task {
                try await client.chatStreaming(message: message, conversation: conversationID,
                                               clientRunID: id, imagePath: attachedImage) { [weak self] frame in
                    guard let self, self.activeRunID == id else { return }
                    if frame.type == "delta", let delta = frame.text {
                        self.liveResponse += delta
                        self.activityLabel = "Ich antworte"
                        let ready = sentences.append(delta)
                        if shouldSpeak && self.speaksReplies && self.voiceForeground {
                            for sentence in ready { self.speech.enqueueSentence(sentence) }
                        }
                    } else if frame.type == "activity", let phase = frame.phase {
                        self.activityLabel = JarvisAPIClient.Activity(phase: phase, tool: frame.tool ?? "").label
                        if phase == "tool", !announcedTool, self.liveResponse.isEmpty,
                           shouldSpeak, self.speaksReplies, self.voiceForeground {
                            announcedTool = true
                            // Only say something that tells the user something.
                            // A web search is worth announcing because it takes
                            // time; the generic case was "Ich prüfe das", which
                            // says nothing, costs a spoken sentence and delays
                            // the actual answer. Silence is the better filler.
                            let tool = (frame.tool ?? "").lowercased()
                            if tool.contains("search") || tool.contains("web") || tool.contains("browser") {
                                self.speech.enqueueSentence("Ich schaue im Web nach.")
                            }
                        }
                    }
                }
            }
            chatTask = pending
            let response = try await pending.value
            guard activeRunID == id else { return }
            activeRunID = nil
            chatTask = nil
            isWorking = false
            let names = response.tools.map(\.name)
            appendMessage(ChatMessage(role: .jarvis, text: response.text, tools: names,
                                      attachments: response.messageAttachments))
            connection = .online
            liveResponse = ""
            if shouldSpeak && speaksReplies && voiceForeground {
                for sentence in sentences.finish(finalText: response.text) { speech.enqueueSentence(sentence) }
                speech.endStream()
            } else {
                speech.stopSpeaking()
                await resumeVoice()
            }
        } catch {
            guard activeRunID == id else { return }
            activeRunID = nil
            chatTask = nil
            isWorking = false
            speech.stopSpeaking()
            liveResponse = ""
            lastError = error.localizedDescription
            connection = .offline(error.localizedDescription)
            appendMessage(ChatMessage(role: .system, text: error.localizedDescription))
        }
    }

    /// Stops the running Hermes turn, not just the local URLSession request.
    /// Barge-in reuses this: the user talking over the answer is a redirection,
    /// so the turn ends silently rather than announcing a cancellation.
    private func cancelActiveRun(announcing: Bool) async {
        guard let id = activeRunID else { return }
        do {
            let client = try makeClient()
            try await client.stop(clientRunID: id)
            guard activeRunID == id else { return }
            activeRunID = nil
            chatTask?.cancel()
            chatTask = nil
            isWorking = false
            liveResponse = ""
            if announcing {
                appendMessage(ChatMessage(role: .system, text: "Anfrage abgebrochen."))
            }
        } catch { lastError = error.localizedDescription }
    }

    func toggleListening() async {
        if isWorking, activeRunID != nil {
            speech.suspend()
            await cancelActiveRun(announcing: true)
            await resumeVoice()
        } else if speech.isSpeaking {
            speech.stopSpeaking()
            await resumeVoice()
        } else if speech.isListening {
            if let text = speech.stop() { await send(text) }
            else { voiceModeEnabled = false }
        } else {
            voiceModeEnabled = true
            await resumeVoice()
        }
    }

#if os(iOS)
    private func sendFromWatch(_ text: String, requestID: String) async -> String {
        let cleanText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanText.isEmpty else { return "Ich habe nichts verstanden." }

        appendMessage(ChatMessage(role: .user, text: cleanText))
        do {
            let client = try makeClient()
            var sentences = SpeechSentenceBuffer()
            let response = try await client.chatStreaming(message: cleanText, conversation: conversation, clientRunID: requestID) { [weak self] frame in
                guard frame.type == "delta", let delta = frame.text else { return }
                for sentence in sentences.append(delta) {
                    self?.watchConnectivityController?.deliverSentence(sentence, id: requestID)
                }
            }
            for sentence in sentences.finish(finalText: response.text) {
                watchConnectivityController?.deliverSentence(sentence, id: requestID)
            }
            appendMessage(ChatMessage(role: .jarvis, text: response.text, tools: response.tools.map(\.name),
                                       attachments: response.messageAttachments))
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
        updateActiveConversation(using: message)
    }

    private func restoreChatHistory() {
        conversations = ChatHistoryStore.load()
            .compactMap { stored -> ChatConversation? in
                let id = stored.id.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !id.isEmpty, id.count <= 80 else { return nil }
                let title = stored.title.trimmingCharacters(in: .whitespacesAndNewlines)
                return ChatConversation(
                    id: id,
                    title: title.isEmpty ? "Neuer Chat" : title,
                    messages: Array(stored.messages.suffix(Self.maximumMessageCount)),
                    updatedAt: stored.updatedAt
                )
            }
            .sorted { $0.updatedAt > $1.updatedAt }
            .prefix(Self.maximumConversationCount - 1)
            .map { $0 }

        let initial = ChatConversation(
            id: conversation,
            title: "Neuer Chat",
            messages: [Self.makeWelcomeMessage()],
            updatedAt: Date()
        )
        messages = initial.messages
        conversations.insert(initial, at: 0)
        // Do not persist an untouched launch placeholder. It is archived by
        // appendMessage as soon as the user actually starts this conversation.
    }

    private func updateActiveConversation(using message: ChatMessage) {
        let now = Date()
        let title = message.role == .user ? Self.title(for: message.text) : nil

        if let index = conversations.firstIndex(where: { $0.id == conversation }) {
            conversations[index].messages = messages
            conversations[index].updatedAt = now
            if conversations[index].title == "Neuer Chat", let title {
                conversations[index].title = title
            }
        } else {
            conversations.append(ChatConversation(
                id: conversation,
                title: title ?? "Neuer Chat",
                messages: messages,
                updatedAt: now
            ))
        }
        storeChatHistory()
    }

    private func storeChatHistory() {
        conversations.sort { $0.updatedAt > $1.updatedAt }
        if conversations.count > Self.maximumConversationCount {
            conversations.removeLast(conversations.count - Self.maximumConversationCount)
        }
        UserDefaults.standard.set(conversation, forKey: "conversation")
        ChatHistoryStore.save(conversations)
    }

    private static func title(for text: String) -> String {
        let compact = text
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        guard compact.count > 48 else { return compact }
        return String(compact.prefix(47)).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
    }

    private static func makeWelcomeMessage() -> ChatMessage {
        ChatMessage(role: .jarvis, text: "System bereit. Womit darf ich helfen?")
    }

    private static func makeConversationID() -> String {
        "jarvis-apple-\(UUID().uuidString.lowercased())"
    }
}
