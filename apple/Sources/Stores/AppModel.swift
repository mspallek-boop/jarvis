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
    /// One task the app is running right now. There used to be a single slot —
    /// `activeRunID` plus one `liveResponse` — so starting a second task
    /// silently orphaned the first: its frames were dropped by an identity
    /// guard and its answer never arrived. That is what "he forgets everything
    /// as soon as I give him a new task" was.
    struct LocalRun: Identifiable {
        let id: String
        let prompt: String
        let startedAt: Date
        var liveResponse = ""
        var activityLabel = "Ich denke nach"
    }

    /// Running tasks, oldest first. Empty means idle.
    @Published private(set) var localRuns: [LocalRun] = []
    /// The task the user is looking at: its answer streams into the view and
    /// the orb tap cancels it. Tapping another blob focuses that one instead.
    @Published var focusedRunID: String?
    @Published private(set) var runs: [JarvisAPIClient.RunStatus] = []
    /// Tasks that outlive the app — a stand-in in one chat, running until its
    /// own clock says stop. The Mac keeps them, so closing the window does not
    /// end them; showing them is the only way the user can tell.
    @Published private(set) var standins: [JarvisAPIClient.Standin] = []
    @Published private(set) var notificationBanner: String?

    var isWorking: Bool { !localRuns.isEmpty }
    private var focusedRun: LocalRun? {
        localRuns.first { $0.id == focusedRunID } ?? localRuns.first
    }
    var activityLabel: String { focusedRun?.activityLabel ?? "Ich denke nach" }
    var liveResponse: String { focusedRun?.liveResponse ?? "" }

    #if os(iOS)
    /// The lock screen's and the Dynamic Island's view of a running turn. It
    /// is the only part of the app that survives the screen going off, so it
    /// is what replaced "Verbindung verloren" with the work still visibly
    /// happening. Every run passes through the three functions below, so the
    /// activity is started, updated and ended from one place each.
    private let liveActivity = LiveActivityController()
    #endif

    private func beginRun(id: String, prompt: String) {
        localRuns.append(LocalRun(id: id, prompt: prompt, startedAt: Date()))
        #if os(iOS)
        liveActivity.start(runID: id, prompt: prompt, phase: "Ich denke nach")
        #endif
    }

    private func updateRun(_ id: String, _ change: (inout LocalRun) -> Void) {
        guard let index = localRuns.firstIndex(where: { $0.id == id }) else { return }
        change(&localRuns[index])
        #if os(iOS)
        liveActivity.update(runID: id, phase: localRuns[index].activityLabel,
                            reply: localRuns[index].liveResponse)
        #endif
    }

    private func finishRun(_ id: String, reply: String = "", failure: String? = nil) {
        #if os(iOS)
        let text = reply.isEmpty
            ? (localRuns.first { $0.id == id }?.liveResponse ?? "")
            : reply
        liveActivity.finish(runID: id, reply: text, failure: failure)
        #endif
        localRuns.removeAll { $0.id == id }
        chatTasks[id]?.cancel()
        chatTasks[id] = nil
        if focusedRunID == id { focusedRunID = localRuns.first?.id }
    }
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
    @Published private(set) var voiceGroups: [JarvisAPIClient.VoiceGroup] = []
    #if os(macOS)
    /// Push-to-talk from anywhere: hold to talk, double-tap for hands-free.
    let hotkey = HotkeyMonitor()
    /// The small panel is shown while the main window is out of the way.
    @Published private(set) var overlayVisible = false
    /// True only for a pill the key summoned out of nothing. The fold is a
    /// decision the user made and stays until they undo it; a summon is a
    /// question they asked, and once it is answered the pill has no business
    /// still being there.
    private var overlaySummoned = false
    private var overlayDismissTask: Task<Void, Never>?
    /// Long enough to add "one more thing", short enough that a finished
    /// exchange does not leave a pill sitting there for the rest of the day.
    private static let summonedOverlayLinger: Double = 9
    private let overlayPanel = OverlayPanelController()

    /// Fold the window into the pill. The pill has to exist first, because the
    /// window animates into *its* rectangle — that shared rectangle is what
    /// makes the two read as one thing.
    func collapseToOverlay() {
        guard !overlayVisible else { return }
        // Folded on purpose: this one stays until the user says otherwise.
        overlaySummoned = false
        overlayDismissTask?.cancel()
        overlayPanel.show(model: self)
        overlayPanel.onClick = { [weak self] in self?.expandFromOverlay() }
        overlayVisible = true
        // Push-to-talk belongs to the small mode only. With the window in front
        // JARVIS listens the way he always did, and a global key grab would
        // fight the app's own microphone handling.
        hotkey.active = true
        // ⌘M reaches the guard above through two notifications whose order is
        // not ours to choose, so the one that arrives first can still find
        // `overlayVisible` false and suspend the voice. Re-asserting after the
        // flag is set makes the outcome independent of that race.
        Task { await setVoiceForeground(true) }
        WindowTransition.collapse(into: overlayPanel.frame) {}
    }

    /// Wake JARVIS when he is away entirely — no window, no pill.
    ///
    /// Closing the window is a legitimate thing to do, and it used to make him
    /// unreachable: `hotkey.active` was raised only by the fold, so with no
    /// window and no pill the key did nothing and the Dock icon was the only
    /// way back. The key is the one thing the user can press without looking,
    /// so it has to be the one thing that always works.
    func wakeToOverlay() {
        guard !overlayVisible else { return }
        overlayPanel.popUp(model: self)
        overlayPanel.onClick = { [weak self] in self?.expandFromOverlay() }
        overlayVisible = true
        overlaySummoned = true
        hotkey.active = true
        // A summon that turns out to be a mis-press should not cost anything
        // either, so the countdown starts with the pill rather than with the
        // first answer.
        scheduleOverlayDismiss()
    }

    /// Wake JARVIS and open the microphone in one go.
    ///
    /// The hands-free double tap on the hotkey and the wake word are two ways
    /// of saying the same thing, so they end up here rather than each growing
    /// their own version of it.
    func wakeAndListen() async {
        // Exactly one of the two on screen, ever — the same rule the fold and
        // the reopen already keep. With the window in front there is nothing to
        // summon: he is standing there. A pill over his own window is two
        // JARVISes, and the wake word must not be the one gesture that produces
        // that.
        if !mainWindowIsOnScreen { wakeToOverlay() }
        speech.setMicrophoneMuted(false)
        await speech.start()
        scheduleOverlayDismiss()
    }

    /// Whether the main window is really in front of the user: not folded into
    /// the pill, not minimised, not closed.
    private var mainWindowIsOnScreen: Bool {
        guard let window = WindowTransition.mainWindow() else { return false }
        return window.isVisible && !window.isMiniaturized
    }

    /// Let a summoned pill sink away once the exchange is over.
    ///
    /// "Over" is silence, not the last spoken word: the microphone stays open
    /// after an answer precisely so the user can carry on, and dropping the
    /// pill the moment JARVIS stops talking would cut that off. So the
    /// countdown restarts instead of firing whenever anything is still going
    /// on — a run, playback, a half-spoken sentence, a held key.
    func scheduleOverlayDismiss() {
        overlayDismissTask?.cancel()
        guard overlaySummoned, overlayVisible else { return }
        overlayDismissTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(Self.summonedOverlayLinger))
            guard !Task.isCancelled, let self, self.overlaySummoned, self.overlayVisible
            else { return }
            // Silence, not an empty transcript: the microphone stays open
            // after an answer, so anything it happened to pick up would
            // otherwise keep the pill alive indefinitely.
            let quietFor = Date().timeIntervalSince(self.speech.lastHeard)
            guard !self.isWorking, !self.speech.isSpeaking,
                  quietFor >= Self.summonedOverlayLinger,
                  !self.hotkey.isHeld, !self.hotkey.handsFree
            else { self.scheduleOverlayDismiss(); return }
            self.dismissSummonedOverlay()
        }
    }

    /// Send the summoned pill back where it came from.
    func dismissSummonedOverlay() {
        guard overlayVisible, overlaySummoned else { return }
        overlayDismissTask?.cancel()
        overlayDismissTask = nil
        overlaySummoned = false
        overlayVisible = false
        // The microphone goes with it. A capture left open behind a pill that
        // is no longer on screen is the "talking into the dark" fault, only
        // with nobody there to notice it.
        speech.suspend()
        // The key stays armed: with no window and no pill, it is the only way
        // back — which is the whole reason `wakeToOverlay` exists.
        hotkey.active = true
        overlayPanel.dropDown {}
    }

    /// The key is armed exactly when the main window is not standing in front
    /// of the user. Called from every path that opens or closes that window,
    /// because "is JARVIS reachable" must not depend on which of them ran.
    func updateHotkeyArming(mainWindowVisible: Bool) {
        hotkey.active = overlayVisible || !mainWindowVisible
    }

    /// Spring the window back out of the pill, centred.
    func expandFromOverlay() {
        guard overlayVisible else { return }
        overlaySummoned = false
        overlayDismissTask?.cancel()
        overlayVisible = false
        hotkey.active = false
        let source = overlayPanel.frame
        NSApp.unhide(nil)
        NSApp.activate(ignoringOtherApps: true)
        if WindowTransition.mainWindow() != nil {
            WindowTransition.expand(from: source)
        } else {
            // The pill can now exist with no window behind it: the hotkey wakes
            // it after the window was *closed*, not folded, and a closed window
            // is deallocated. `expand` would find nothing and return silently —
            // the pill would fade and leave nothing at all, which is worse than
            // where we started. Asking Launch Services to open the running app
            // delivers a reopen, and SwiftUI answers that by building a window.
            NSWorkspace.shared.open(Bundle.main.bundleURL)
        }
        // The pill fades while the window grows out of it, so for a moment both
        // occupy the same place — which is what sells one as becoming the other.
        overlayPanel.fadeOut(duration: WindowTransition.expandDuration * 0.5) {}
    }
    private var hotkeyObserver: AnyCancellable?
    #endif
    @Published private(set) var voiceListError: String?
    @Published var selectedBridgeVoice: String = "" {
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
            || isUploadingImage
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
            voiceGroups = response.displayGroups
            availableBridgeVoices = voiceGroups.flatMap(\.voices)
            voiceListError = availableBridgeVoices.isEmpty
                ? "Keine Stimmen verfügbar. Läuft Piper auf dem Mac?"
                : nil
            // A voice removed on the Mac must not stay selected here.
            if !selectedBridgeVoice.isEmpty,
               !availableBridgeVoices.contains(where: { $0.id == selectedBridgeVoice }) {
                selectedBridgeVoice = ""
            }
        } catch {
            voiceGroups = []
            availableBridgeVoices = []
            voiceListError = error.localizedDescription
        }
    }
    private var chatTasks: [String: Task<JarvisAPIClient.ChatResponse, Error>] = [:]
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
        // The app no longer sends provider voice IDs. Forget a previously
        // selected ElevenLabs voice so an offline launch cannot reuse it.
        UserDefaults.standard.removeObject(forKey: "selectedBridgeVoice")
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
                // Speaking while a turn runs used to cancel it. A new task is
                // not a correction: it is added and both run. Cancelling is the
                // orb tap, which is explicit and reversible in a way that
                // losing minutes of work is not.
                await self.send(text)
            }
        }
        // The countdown must not end the microphone mid-turn: while a run is
        // going, silence means the user is listening, not gone.
        speech.shouldKeepListening = { [weak self] in self?.isWorking ?? false }
        speech.onSpeechFinished = { [weak self] in
            Task {
                await self?.resumeVoice()
                #if os(macOS)
                // He has finished talking, so the silence that decides whether
                // a summoned pill stays starts here.
                self?.scheduleOverlayDismiss()
                #endif
            }
        }
        #if os(macOS)
        // Holding the key opens the microphone even when the app is not in
        // front, which is the point — dictating into another app.
        hotkey.onPressAndHold = { [weak self] in
            Task { @MainActor in
                guard let self else { return }
                // Before the microphone, the pill: talking to something with no
                // sign of itself on screen is talking into the dark, and the
                // user cannot tell a listening JARVIS from a broken one.
                self.wakeToOverlay()
                self.speech.setMicrophoneMuted(false)
                await self.speech.start()
            }
        }
        // Letting go ends the sentence and sends it, rather than waiting for
        // the silence timer: the release *is* the end of the sentence.
        hotkey.onRelease = { [weak self] in
            Task { @MainActor in
                guard let self, !self.hotkey.handsFree else { return }
                if let text = self.speech.stop() { await self.send(text) }
            }
        }
        hotkey.onHandsFreeChanged = { [weak self] on in
            Task { @MainActor in
                guard let self else { return }
                if on {
                    self.wakeToOverlay()
                    self.speech.setMicrophoneMuted(false)
                    await self.speech.start()
                } else if let text = self.speech.stop() {
                    await self.send(text)
                }
            }
        }
        hotkeyObserver = hotkey.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
        #endif
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

    /// True when a request failed only because iOS froze the app.
    ///
    /// A locked screen suspends the process and tears down its sockets. The
    /// URLSession error that arrives is indistinguishable from a real outage —
    /// "Die Netzwerkverbindung wurde unterbrochen" — so treating it as one is
    /// what put a permanent offline banner and a red system line in the chat
    /// every time the phone went dark. It is not an outage; it is a pause.
    private func isSuspensionDrop(_ error: Error) -> Bool {
        guard !voiceForeground else { return false }
        let code = (error as? URLError)?.code
        if case .timedOut = (error as? JarvisAPIClient.ClientError) { return true }
        return code == .networkConnectionLost || code == .cancelled
            || code == .notConnectedToInternet || code == .timedOut
    }

    /// Records a failed request, unless the phone simply went to sleep on it.
    private func recordFailure(_ error: Error, announce: Bool = true) {
        if isSuspensionDrop(error) {
            // Say nothing and claim nothing. `unchecked` is honest — we do not
            // know — and the next foreground check answers it for real.
            connection = .unchecked
            return
        }
        lastError = error.localizedDescription
        connection = .offline(error.localizedDescription)
        if announce { appendMessage(ChatMessage(role: .system, text: error.localizedDescription)) }
    }

    /// Called when the app comes back to the front, including after the screen
    /// was merely off. Nothing else re-checks: `checkConnection` runs from the
    /// view's `task`, which does not run again for a scene that never went
    /// away, so a stale offline state used to survive until the app was killed.
    func resumeFromBackground() async {
        await checkConnection()
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
            recordFailure(error, announce: false)
        }
    }

    private func refreshStatus() async {
        guard !token.isEmpty else { return }
        do {
            let client = try makeClient()
            runs = try await client.runs().runs
            standins = try await client.standins()
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
            // Once straight away: a stand-in that is already running would
            // otherwise be invisible for the first eighteen seconds, which is
            // exactly when the user is looking.
            await self?.refreshStatus()
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
        #if os(macOS)
        // Folding the window away is not leaving. Every path that hides the
        // main window — ⌘H, ⌘M, the fold, `onDisappear`, the scene going to
        // background — ends up here with `false`, and `false` means
        // `speech.suspend()`, which throws away the sentence queue and cuts off
        // whatever is being read out mid-word. While the pill is up JARVIS is
        // still on screen and still working, so the pill is the one case where
        // "the window went away" must not be answered with "stop".
        if !active && overlayVisible { return }
        #endif
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
        // Not gated on `isWorking` any more: a task that is still running is
        // precisely when the user may want to hand over the next one.
        guard !speech.isSpeaking else { return }
        await speech.start()
    }

    func send(_ explicitText: String? = nil) async {
        let text = (explicitText ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard (!text.isEmpty || !pendingImagePath.isEmpty), !isUploadingImage else { return }
        let message = text.isEmpty ? "Was ist auf diesem Bild zu sehen?" : text
        // Something already running means this is a second task, so it gets a
        // lane of its own instead of queueing behind the first.
        let runsInParallel = !localRuns.isEmpty
        if voiceModeEnabled && voiceForeground {
            // Keep hearing the user through thinking and speaking alike. Even
            // with barge-in switched off the microphone stays open while JARVIS
            // thinks — thinking is silent, so there is no echo to guard against,
            // and that is exactly the window in which a second task is handed
            // over. `play` closes the capture again once the answer talks.
            await speech.listenThrough()
        } else if !runsInParallel {
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
        let id = UUID().uuidString
        beginRun(id: id, prompt: message)
        // A new task is what the user just asked for, so it is what they are
        // looking at. The older one keeps running and stays reachable.
        focusedRunID = id
        var sentences = SpeechSentenceBuffer()
        var announcedTool = false
        // Only the focused task may speak. Two answers read aloud at once are
        // unintelligible, and the second one is not what the user is watching.
        let shouldSpeak = speaksReplies && voiceForeground
        do {
            let client = try makeClient()
            if shouldSpeak { speech.beginStream(client: client) }
            let conversationID = conversation
            let pending = Task {
                try await client.chatStreaming(message: message, conversation: conversationID,
                                               clientRunID: id, imagePath: attachedImage,
                                               parallel: runsInParallel) { [weak self] frame in
                    // Guard on this run still existing, never on it being the
                    // active one — that identity check is what dropped the
                    // first task's frames the moment a second one started.
                    guard let self, self.localRuns.contains(where: { $0.id == id }) else { return }
                    let isFocused = self.focusedRunID == id
                    if frame.type == "delta", let delta = frame.text {
                        self.updateRun(id) { $0.liveResponse += delta; $0.activityLabel = "Ich antworte" }
                        let ready = sentences.append(delta)
                        if shouldSpeak && isFocused && self.speaksReplies && self.voiceForeground {
                            for sentence in ready { self.speech.enqueueSentence(sentence) }
                        }
                    } else if frame.type == "activity", let phase = frame.phase {
                        let label = JarvisAPIClient.Activity(phase: phase, tool: frame.tool ?? "").label
                        self.updateRun(id) { $0.activityLabel = label }
                        let quiet = self.localRuns.first { $0.id == id }?.liveResponse.isEmpty ?? true
                        if phase == "tool", !announcedTool, quiet, isFocused,
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
            chatTasks[id] = pending
            let response = try await pending.value
            guard localRuns.contains(where: { $0.id == id }) else { return }
            let wasFocused = focusedRunID == id
            finishRun(id, reply: response.text)
            let names = response.tools.map(\.name)
            appendMessage(ChatMessage(role: .jarvis, text: response.text, tools: names,
                                      attachments: response.messageAttachments))
            connection = .online
            if shouldSpeak && wasFocused && speaksReplies && voiceForeground {
                for sentence in sentences.finish(finalText: response.text) { speech.enqueueSentence(sentence) }
                speech.endStream()
            } else if !isWorking {
                speech.stopSpeaking()
                await resumeVoice()
                #if os(macOS)
                scheduleOverlayDismiss()
                #endif
            }
        } catch {
            guard localRuns.contains(where: { $0.id == id }) else { return }
            let wasFocused = focusedRunID == id
            finishRun(id, failure: isSuspensionDrop(error) ? nil : error.localizedDescription)
            if wasFocused { speech.stopSpeaking() }
            recordFailure(error)
            #if os(macOS)
            // A failed turn is still a finished one; the pill must not be left
            // standing there because the answer never came.
            scheduleOverlayDismiss()
            #endif
        }
    }

    /// Stops one Hermes turn, not just the local URLSession request.
    /// Cancels the focused task only — the others were not what the user
    /// pointed at, and stopping work nobody asked to stop is the failure this
    /// whole change exists to remove.
    func cancelRun(_ runID: String? = nil, announcing: Bool) async {
        guard let id = runID ?? focusedRunID ?? localRuns.first?.id else { return }
        do {
            let client = try makeClient()
            try await client.stop(clientRunID: id)
            guard localRuns.contains(where: { $0.id == id }) else { return }
            finishRun(id)
            if announcing {
                appendMessage(ChatMessage(role: .system, text: "Anfrage abgebrochen."))
            }
        } catch { lastError = error.localizedDescription }
    }

    /// Bring another running task into view. The blobs call this.
    func focusRun(_ runID: String) {
        guard localRuns.contains(where: { $0.id == runID }) else { return }
        speech.stopSpeaking()      // the old task's answer is no longer the one being read
        focusedRunID = runID
    }

    func toggleListening() async {
        if isWorking {
            speech.suspend()
            await cancelRun(announcing: true)
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
            recordFailure(error)
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
