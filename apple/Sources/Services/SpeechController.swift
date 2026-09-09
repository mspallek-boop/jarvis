import AVFoundation
import Foundation
import Speech

struct SpeechVoiceOption: Identifiable {
    let id: String
    let name: String
    let qualityLabel: String

    var label: String {
        qualityLabel.isEmpty ? name : "\(name) · \(qualityLabel)"
    }
}

/// Hands audio buffers from the capture thread to whichever recogniser request
/// is current. `SFSpeechRecognizer` closes its request at the first pause it
/// hears, so the request is replaced underneath a tap that keeps running — the
/// tap must therefore never hold one directly.
private final class RequestBox: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    func replace(with new: SFSpeechAudioBufferRecognitionRequest?) {
        lock.lock()
        let old = request
        request = new
        lock.unlock()
        old?.endAudio()
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        defer { lock.unlock() }
        request?.append(buffer)
    }
}

@MainActor
final class SpeechController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    private static let voiceDefaultsKey = "speechVoiceIdentifier"
    private static let vocabularyDefaultsKey = "recognitionVocabulary"
    private static let timeoutDefaultsKey = "listeningTimeout"
    private static let pauseDefaultsKey = "utterancePause"
    /// Long enough to gather a thought, short enough that the microphone is not
    /// simply always on.
    static let defaultListeningTimeout: Double = 30
    static let defaultVocabulary = ["Skyr", "JARVIS", "Hermes", "Tailscale", "Marlon"]
    private static let preferredGermanVoiceNames = [
        "Yannick", "Martin", "Markus", "Daniel", "Anna"
    ]

    @Published private(set) var isSpeaking = false
    /// Hard mute for the microphone, so the user can talk to someone else
    /// without JARVIS listening in. Every path that opens the microphone goes
    /// through `start(stoppingSpeech:)`, so gating it there is what makes this
    /// airtight — barge-in, the idle restart and `listenThrough()` all obey it
    /// without needing their own check.
    @Published private(set) var microphoneMuted = UserDefaults.standard.bool(forKey: "microphoneMuted")
    var onUtterance: ((String) -> Void)?
    var onSpeechFinished: (() -> Void)?
    private static var permissionRequest: Task<Bool, Never>?
    private static var permissionAttempted = false
    private var silenceTask: Task<Void, Never>?
    private var bargeIn = BargeInDetector()
    private var idleTask: Task<Void, Never>?
    /// AppModel answers whether a turn is still running. The microphone must
    /// outlive the silence while JARVIS is thinking, or barge-in is pointless.
    var shouldKeepListening: (() -> Bool)?
    /// How long a pause may be before the sentence counts as finished. 850ms
    /// cut people off mid-thought; a breath between clauses is not an ending.
    /// 1.6s was still too short, because this timer does not measure silence —
    /// it measures the transcript standing still, and the on-device recogniser
    /// lags behind the voice by a good part of a second.
    @Published var utterancePause: Double = UserDefaults.standard.object(forKey: "utterancePause") as? Double ?? 2.5 {
        didSet { UserDefaults.standard.set(utterancePause, forKey: Self.pauseDefaultsKey) }
    }
    /// Seconds of silence after which listening stops. Zero means never.
    @Published var listeningTimeout: Double = UserDefaults.standard.object(forKey: "listeningTimeout") as? Double
        ?? SpeechController.defaultListeningTimeout {
        didSet { UserDefaults.standard.set(listeningTimeout, forKey: Self.timeoutDefaultsKey) }
    }
    /// Echo cancellation is not available on every device. Without it the
    /// microphone hears the answer and would cut it off immediately, so
    /// barge-in stays off rather than breaking playback.
    private var bargeInAvailable = true
    private var captureID = UUID()
    private var tapInstalled = false
    private var activeUtterance: AVSpeechUtterance?
    private let neuralPlayer = NeuralSpeechPlayer()
    private var neuralTask: Task<Void, Never>?
    private var speechGeneration = UUID()
    private var queuedSentences: [String] = []
    private var streamIsOpen = false
    /// True once this stream has actually produced sound. Until then nothing is
    /// coming out of the speaker, so what the microphone hears is the user.
    private var hasPlayedInStream = false
    private var streamClient: JarvisAPIClient?
    @Published var playbackSpeed = SpeechPlaybackSpeed.load() {
        didSet {
            playbackSpeed.save()
            neuralPlayer.playbackSpeed = playbackSpeed
        }
    }
    @Published var usesNaturalVoice = UserDefaults.standard.object(forKey: "usesNaturalVoice") as? Bool ?? true {
        didSet { UserDefaults.standard.set(usesNaturalVoice, forKey: "usesNaturalVoice") }
    }
    /// Stop reading aloud as soon as the user starts talking, instead of
    /// requiring a tap on the orb.
    @Published var interruptsBySpeaking = UserDefaults.standard.object(forKey: "interruptsBySpeaking") as? Bool ?? true {
        didSet { UserDefaults.standard.set(interruptsBySpeaking, forKey: "interruptsBySpeaking") }
    }
    /// Words the German on-device recogniser does not know — brand and product
    /// names such as "Skyr", which it otherwise renders as "Skar".
    @Published var recognitionVocabulary: [String] = SpeechController.storedVocabulary() {
        didSet { UserDefaults.standard.set(recognitionVocabulary, forKey: Self.vocabularyDefaultsKey) }
    }
    @Published private(set) var isListening = false
    @Published private(set) var transcript = ""
    /// When the transcript last grew. "Is the user still talking?" is a
    /// question about the last few seconds — an empty transcript is not the
    /// same thing, and a single cough would otherwise count as talking for
    /// the rest of the session.
    @Published private(set) var lastHeard = Date.distantPast
    @Published var errorMessage: String?
    @Published var selectedVoiceIdentifier: String {
        didSet {
            UserDefaults.standard.set(selectedVoiceIdentifier, forKey: Self.voiceDefaultsKey)
        }
    }

    @Published private(set) var availableGermanVoices: [SpeechVoiceOption]
    @Published private(set) var hasEnhancedGermanVoice: Bool

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "de-DE"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    /// The tap runs on an audio thread and the request behind it is swapped
    /// every time a recognition segment closes, so the tap cannot capture one.
    private let requestBox = RequestBox()
    /// Words from recognition segments Apple has already closed. The live
    /// segment is appended to this, which is what makes a pause survivable.
    private var committedTranscript = ""
    /// Identifies the live recognition segment. A callback from a segment that
    /// has already been replaced must not write over the current transcript.
    private var segmentID = UUID()
    /// A recogniser that fails on every restart must not be restarted forever.
    /// Past this the utterance is handed over rather than dropped.
    private var segmentRestarts = 0
    private static let maxSegmentRestarts = 24
    private let synthesizer = AVSpeechSynthesizer()
    private var isStarting = false

    override init() {
        let voices = Self.germanVoices()
        availableGermanVoices = voices.map {
            SpeechVoiceOption(
                id: $0.identifier,
                name: $0.name,
                qualityLabel: Self.qualityLabel(for: $0)
            )
        }
        hasEnhancedGermanVoice = voices.contains { $0.quality.rawValue > 1 }

        let storedIdentifier = UserDefaults.standard.string(forKey: Self.voiceDefaultsKey)
        if let storedIdentifier, voices.contains(where: { $0.identifier == storedIdentifier }) {
            selectedVoiceIdentifier = storedIdentifier
        } else {
            selectedVoiceIdentifier = voices.first?.identifier ?? ""
        }
        super.init()
        synthesizer.delegate = self
        neuralPlayer.playbackSpeed = playbackSpeed
    }

    private static func storedVocabulary() -> [String] {
        let stored = UserDefaults.standard.stringArray(forKey: vocabularyDefaultsKey)
        return stored ?? defaultVocabulary
    }

    func refreshVoices() {
        let voices = Self.germanVoices()
        availableGermanVoices = voices.map {
            SpeechVoiceOption(id: $0.identifier, name: $0.name, qualityLabel: Self.qualityLabel(for: $0))
        }
        hasEnhancedGermanVoice = voices.contains { $0.quality.rawValue > 1 }
        let selected = voices.first { $0.identifier == selectedVoiceIdentifier }
        if selected == nil || (selected!.quality.rawValue == 1 && hasEnhancedGermanVoice) {
            selectedVoiceIdentifier = voices.first?.identifier ?? ""
        }
    }

    func toggle() async -> String? {
        if isListening { return stop() }
        await start()
        return nil
    }

    /// Mute or unmute the microphone. Muting closes the capture immediately —
    /// a mute that only takes effect at the next turn is not a mute.
    func setMicrophoneMuted(_ muted: Bool) {
        guard muted != microphoneMuted else { return }
        microphoneMuted = muted
        UserDefaults.standard.set(muted, forKey: "microphoneMuted")
        if muted { finishAudio() }
    }

    func start(stoppingSpeech: Bool = true) async {
        guard !microphoneMuted else { return }
        guard !isListening, !isStarting else { return }
        isStarting = true
        let id = UUID()
        captureID = id
        defer { isStarting = false }
        errorMessage = nil
        refreshVoices()
        guard await requestPermissions() else {
            errorMessage = "Mikrofon oder Spracherkennung ist nicht freigegeben. Du kannst unten tippen."
            return
        }
        guard captureID == id, !Task.isCancelled else { return }
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Spracherkennung ist gerade nicht verfügbar. Tippe auf JARVIS, um es erneut zu versuchen."
            return
        }
        if stoppingSpeech { stopSpeaking() }
        transcript = ""
        committedTranscript = ""
        segmentRestarts = 0

        do {
            #if os(iOS)
            let session = AVAudioSession.sharedInstance()
            // .voiceChat engages the system echo canceller, without which the
            // microphone hears our own answer and barge-in fires on itself.
            try session.setCategory(.playAndRecord,
                                    mode: interruptsBySpeaking ? .voiceChat : .default,
                                    options: [.defaultToSpeaker, .allowBluetoothHFP])
            try session.setActive(true)
            #endif
            let input = engine.inputNode
            if interruptsBySpeaking {
                do {
                    try input.setVoiceProcessingEnabled(true)
                    bargeInAvailable = true
                } catch {
                    // Losing the microphone would be worse than losing barge-in.
                    bargeInAvailable = false
                }
            }
            // Voice processing changes the input format, so read it afterwards.
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                finishAudio()
                errorMessage = "Kein Mikrofon verfügbar."
                return
            }
            // Echo cancellation turns this Mac's input into seven channels
            // tagged DiscreteInOrder — and measurement shows all seven carry
            // the identical microphone signal. AVAudioConverter cannot map that
            // layout to mono and silently emits zeroes, which is what left the
            // recogniser deaf. Copying channel 0 keeps the signal byte for byte.
            let monoFormat = format.channelCount > 1
                ? AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: format.sampleRate,
                                channels: 1, interleaved: false)
                : nil
            // The recogniser has to exist before audio flows, or the first
            // word of the sentence lands in an empty box.
            isListening = true
            startRecognitionSegment(capture: id)
            let box = requestBox
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                guard let monoFormat, !buffer.format.isInterleaved,
                      let source = buffer.floatChannelData,
                      let mono = AVAudioPCMBuffer(pcmFormat: monoFormat,
                                                  frameCapacity: buffer.frameLength),
                      let destination = mono.floatChannelData else {
                    box.append(buffer)
                    return
                }
                mono.frameLength = buffer.frameLength
                destination[0].update(from: source[0], count: Int(buffer.frameLength))
                box.append(mono)
            }
            tapInstalled = true
            engine.prepare()
            try engine.start()
            scheduleIdleStop()
        } catch {
            finishAudio()
            errorMessage = "Mikrofon konnte nicht gestartet werden."
        }
    }

    /// Open one recognition segment on the running capture.
    ///
    /// `SFSpeechRecognizer` ends a segment at the first pause it hears: it
    /// reports `isFinal` and the task dies. Treating that as the end of the
    /// sentence is what cut people off mid-thought and — when the segment ended
    /// with an error instead — threw the whole dictated sentence away. A closed
    /// segment now only ends the *segment*: the words are kept and a new one is
    /// opened, so nothing but the silence timer decides when the user is done.
    private func startRecognitionSegment(capture: UUID) {
        guard let recognizer, captureID == capture else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        // The on-device German model does not know product or brand names and
        // renders "Skyr" as "Skar". These bias it without leaving the device.
        request.contextualStrings = recognitionVocabulary
        self.request = request
        requestBox.replace(with: request)

        let segment = UUID()
        segmentID = segment
        task?.cancel()
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self, self.captureID == capture, self.segmentID == segment,
                      self.isListening else { return }
                if let result {
                    let text = Self.joined(self.committedTranscript,
                                           result.bestTranscription.formattedString)
                    if self.echoIsInFlight {
                        // While JARVIS talks — and in the gaps between two
                        // streamed sentences, where its echo is still
                        // arriving — a partial result is only interesting
                        // as evidence that the user cut in.
                        guard self.interruptsBySpeaking, self.bargeInAvailable,
                              self.bargeIn.shouldInterrupt(partial: text) else { return }
                        self.stopSpeaking()
                    }
                    if text != self.transcript {
                        self.transcript = text
                        self.lastHeard = Date()
                        // Words arrived, so the recogniser is healthy: the
                        // restart budget is about a recogniser that is not.
                        self.segmentRestarts = 0
                        self.scheduleEndOfUtterance(id: capture)
                        self.scheduleIdleStop()
                    }
                    if result.isFinal {
                        self.closeSegment(keeping: text, capture: capture)
                        return
                    }
                }
                if error != nil {
                    // On-device recognition errors out as a matter of course —
                    // a stretch of silence, a segment timeout. Ending the
                    // capture here is what made the sentence disappear.
                    self.closeSegment(keeping: self.transcript, capture: capture)
                }
            }
        }
    }

    /// Keep what the closed segment heard and open the next one.
    private func closeSegment(keeping text: String, capture: UUID) {
        committedTranscript = text
        transcript = text
        guard segmentRestarts < Self.maxSegmentRestarts else {
            // The recogniser is not coming back. Hand over what was said
            // rather than discarding it — and if it never heard anything,
            // say so, or the microphone just dies without a word.
            if transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                finishAudio()
                errorMessage = "Sprachaufnahme beendet. Tippe auf JARVIS, um weiterzusprechen."
            } else {
                completeUtterance()
            }
            return
        }
        segmentRestarts += 1
        startRecognitionSegment(capture: capture)
    }

    private static func joined(_ committed: String, _ segment: String) -> String {
        if committed.isEmpty { return segment }
        if segment.isEmpty { return committed }
        return committed + " " + segment
    }

    /// Stops listening after a stretch of silence, so the microphone is not
    /// left open all evening. Restarted by tapping the orb.
    private func scheduleIdleStop() {
        idleTask?.cancel()
        guard listeningTimeout > 0 else { return }
        let seconds = listeningTimeout
        idleTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(seconds)) } catch { return }
            guard let self, self.isListening else { return }
            // Silence during an answer is not idleness — that is exactly when
            // the user may still cut in.
            if self.isSpeaking || self.streamIsOpen || self.shouldKeepListening?() == true {
                self.scheduleIdleStop()
                return
            }
            self.finishAudio()
        }
    }

    private func scheduleEndOfUtterance(id: UUID) {
        silenceTask?.cancel()
        let pause = utterancePause
        silenceTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(pause)) } catch { return }
            guard let self, self.captureID == id, self.isListening else { return }
            self.completeUtterance()
        }
    }

    private func completeUtterance() {
        if let text = stop() { onUtterance?(text) }
    }

    func suspend() {
        finishAudio()
        stopSpeaking()
    }

    func stopSpeaking() {
        queuedSentences = []
        streamIsOpen = false
        hasPlayedInStream = false
        // Nothing is coming out of the speaker any more, so the user's words
        // must stop being mistaken for our own echo.
        bargeIn.stoppedSpeaking()
        streamClient = nil
        stopCurrentOutput()
    }

    private func stopCurrentOutput() {
        speechGeneration = UUID()
        neuralTask?.cancel()
        neuralTask = nil
        neuralPlayer.stop()
        activeUtterance = nil
        isSpeaking = false
        synthesizer.stopSpeaking(at: .immediate)
    }

    func stop() -> String? {
        let result = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        finishAudio()
        return result.isEmpty ? nil : result
    }

    func beginStream(client: JarvisAPIClient) {
        // Deliberately not `suspend()`. Closing the capture here is what made
        // the microphone deaf for the whole thinking phase: the answer had not
        // started yet, so there was no echo to protect against — only a user
        // who could not hand over a second task while the first one ran.
        stopSpeaking()
        streamIsOpen = true
        hasPlayedInStream = false
        streamClient = client
    }

    func enqueueSentence(_ text: String) {
        guard streamIsOpen, !text.isEmpty else { return }
        queuedSentences.append(text)
        if !isSpeaking { playNextSentence() }
    }

    func endStream() {
        streamIsOpen = false
        if !isSpeaking { playNextSentence() }
    }

    private func playNextSentence() {
        if !queuedSentences.isEmpty {
            let next = queuedSentences.removeFirst()
            play(next, neuralClient: streamClient)
        } else if !streamIsOpen {
            streamClient = nil
            bargeIn.stoppedSpeaking()
            // The countdown kept rescheduling itself all through the answer, so
            // whatever was left of it was arbitrary — sometimes a full pause,
            // sometimes none. Your turn to speak starts now, so it starts now.
            if isListening { scheduleIdleStop() }
            onSpeechFinished?()
        }
    }

    private func outputFinished() {
        isSpeaking = false
        neuralTask = nil
        playNextSentence()
    }

    func speak(_ text: String, neuralClient: JarvisAPIClient? = nil) {
        stopSpeaking()
        play(text, neuralClient: neuralClient)
    }

    /// True only while our own voice can still be arriving at the microphone:
    /// during playback, and in the gaps between two sentences of one stream.
    /// A stream that has not spoken yet is JARVIS thinking, and speech heard
    /// then is a new task, not an interruption.
    private var echoIsInFlight: Bool { isSpeaking || (streamIsOpen && hasPlayedInStream) }

    /// True while the microphone is meant to keep running through playback.
    private var listensWhileSpeaking: Bool { interruptsBySpeaking && bargeInAvailable }

    /// Barge-in needs a live recogniser during playback. AppModel suspends the
    /// microphone before every request, so playback has to bring it back.
    /// Continuous listening: the microphone stays open while JARVIS thinks and
    /// while it speaks, so the user can cut in at any moment. A no-op when
    /// already listening, so it is safe to call on every transition.
    func listenThrough() async {
        // Deliberately not gated on bargeInAvailable. Echo cancellation decides
        // whether we may listen *while speaking*, never whether we listen at
        // all — gating this was why the microphone stayed dead after the idle
        // timeout on a machine where voice processing is unavailable.
        await start(stoppingSpeech: isSpeaking && !listensWhileSpeaking)
    }

    private func ensureBargeInCapture() {
        guard listensWhileSpeaking, !isListening, !isStarting else { return }
        Task { [weak self] in await self?.start(stoppingSpeech: false) }
    }

    private func play(_ text: String, neuralClient: JarvisAPIClient?) {
        errorMessage = nil
        hasPlayedInStream = true
        if listensWhileSpeaking {
            bargeIn.nowSpeaking(text)
        } else {
            finishAudio()
        }
        neuralPlayer.managesAudioSession = !listensWhileSpeaking
        stopCurrentOutput()
        if usesNaturalVoice, let neuralClient {
            let id = UUID()
            speechGeneration = id
            isSpeaking = true
            neuralTask = Task { [weak self] in
                guard let self else { return }
                do {
                    try await neuralPlayer.stream(text: text, client: neuralClient) { [weak self] in
                        guard let self, self.speechGeneration == id else { return }
                        self.outputFinished()
                    }
                } catch {
                    guard speechGeneration == id, !Task.isCancelled else { return }
                    let started = neuralPlayer.hasScheduledAudio
                    neuralPlayer.stop()
                    if started {
                        isSpeaking = false
                        errorMessage = "Sprachausgabe unterbrochen. Die Antwort steht im Verlauf."
                        outputFinished()
                    } else {
                        speakSystem(text)
                    }
                }
            }
        } else {
            speakSystem(text)
        }
        ensureBargeInCapture()
    }

    private func speakSystem(_ text: String) {
        refreshVoices()
        if !listensWhileSpeaking { finishAudio() }
        stopCurrentOutput()
        #if os(iOS)
        do {
            let session = AVAudioSession.sharedInstance()
            // Claiming .playback here would end the recording barge-in needs.
            if !listensWhileSpeaking {
                try session.setCategory(.playback, mode: .spokenAudio, options: .duckOthers)
            }
            try session.setActive(true)
        } catch {
            errorMessage = "Sprachausgabe konnte nicht gestartet werden."
            outputFinished()
            return
        }
        #endif
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(identifier: selectedVoiceIdentifier)
            ?? Self.germanVoices().first
            ?? AVSpeechSynthesisVoice(language: "de-DE")
        // A neutral pitch and small pauses sound less synthetic than the old,
        // deliberately lowered voice. The voice asset itself still matters most.
        utterance.rate = playbackSpeed.systemSpeechRate
        utterance.pitchMultiplier = 1.0
        utterance.preUtteranceDelay = 0.02
        utterance.postUtteranceDelay = 0.08
        activeUtterance = utterance
        isSpeaking = true
        synthesizer.speak(utterance)
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.activeUtterance === utterance else { return }
            self.activeUtterance = nil
            self.isSpeaking = false
            #if os(iOS)
            if !self.listensWhileSpeaking {
                try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            }
            #endif
            self.outputFinished()
        }
    }

    private static func germanVoices() -> [AVSpeechSynthesisVoice] {
        AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.lowercased().hasPrefix("de") && !$0.identifier.contains("eloquence") }
            .sorted { lhs, rhs in
                if lhs.quality.rawValue != rhs.quality.rawValue {
                    return lhs.quality.rawValue > rhs.quality.rawValue
                }
                let lhsRank = preferredVoiceRank(lhs.name)
                let rhsRank = preferredVoiceRank(rhs.name)
                if lhsRank != rhsRank { return lhsRank < rhsRank }
                return lhs.name.localizedStandardCompare(rhs.name) == .orderedAscending
            }
    }

    private static func preferredVoiceRank(_ name: String) -> Int {
        preferredGermanVoiceNames.firstIndex {
            name.localizedCaseInsensitiveContains($0)
        } ?? preferredGermanVoiceNames.count
    }

    private static func qualityLabel(for voice: AVSpeechSynthesisVoice) -> String {
        switch voice.quality.rawValue {
        case 3...: return "Premium"
        case 2: return "Erweitert"
        default: return ""
        }
    }

    private func finishAudio() {
        captureID = UUID()
        segmentID = UUID()
        idleTask?.cancel()
        idleTask = nil
        silenceTask?.cancel()
        silenceTask = nil
        engine.stop()
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        requestBox.replace(with: nil)
        task?.cancel()
        task = nil
        request = nil
        committedTranscript = ""
        isListening = false
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    private func requestPermissions() async -> Bool {
        // All windows share one permission request. A denied/undetermined result
        // never triggers another system dialog during this process lifetime.
        if SFSpeechRecognizer.authorizationStatus() == .authorized {
            #if os(iOS)
            if AVAudioApplication.shared.recordPermission == .granted { return true }
            #else
            if AVCaptureDevice.authorizationStatus(for: .audio) == .authorized { return true }
            #endif
        }
        if let pending = Self.permissionRequest { return await pending.value }
        guard !Self.permissionAttempted else { return false }
        Self.permissionAttempted = true
        let pending = Task { @MainActor in
            guard await self.requestSpeechPermissionIfNeeded() else { return false }
            return await self.requestMicrophonePermissionIfNeeded()
        }
        Self.permissionRequest = pending
        let allowed = await pending.value
        Self.permissionRequest = nil
        return allowed
    }

    private func requestSpeechPermissionIfNeeded() async -> Bool {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized:
            return true
        case .notDetermined:
            let status = await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
            }
            return status == .authorized
        case .denied, .restricted:
            return false
        @unknown default:
            return false
        }
    }

    private func requestMicrophonePermissionIfNeeded() async -> Bool {
        #if os(iOS)
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            return true
        case .undetermined:
            return await withCheckedContinuation { continuation in
                AVAudioApplication.requestRecordPermission { continuation.resume(returning: $0) }
            }
        case .denied:
            return false
        @unknown default:
            return false
        }
        #else
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return true
        case .notDetermined:
            return await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { continuation.resume(returning: $0) }
            }
        case .denied, .restricted:
            return false
        @unknown default:
            return false
        }
        #endif
    }
}
