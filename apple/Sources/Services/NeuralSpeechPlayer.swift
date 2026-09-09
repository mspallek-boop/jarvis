import AVFoundation
import Foundation

/// Plays authenticated PCM chunks as they arrive; never stores speech on disk.
///
/// Sentences are fetched ahead of playback, not after it. The previous shape
/// spoke a sentence, waited for the last sample to leave the speaker, tore the
/// engine down and only then asked for the next sentence — so every sentence
/// boundary cost a full round trip to the speech provider. Measured against
/// OpenAI that is six tenths of a second to well over a second, on every
/// boundary, which is what made JARVIS sound like he was thinking between each
/// sentence when he was merely waiting for a download.
///
/// Now one feeder task pulls sentences as fast as the network allows and
/// schedules their buffers into a player node that is never stopped in
/// between. Scheduling does not wait for playback, so the fetch for the next
/// sentence overlaps the playing of the current one and the seam disappears.
@MainActor
final class NeuralSpeechPlayer {
    private let engine: AVAudioEngine
    private let player = AVAudioPlayerNode()
    private let timePitch = AVAudioUnitTimePitch()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1)!
    private var generation = UUID()
    /// While barge-in listens during playback, SpeechController owns the audio
    /// session as .playAndRecord. Claiming .playback here would end recording.
    var managesAudioSession = true
    private(set) var hasScheduledAudio = false
    /// Updating the running effect also changes buffers already scheduled.
    var playbackSpeed: SpeechPlaybackSpeed = .normal {
        didSet { timePitch.rate = Float(playbackSpeed.rawValue) }
    }

    // MARK: queue state

    private var feeder: Task<Void, Never>?
    private var waiting: [String] = []
    /// Set once the caller says no more sentences are coming, so the feeder
    /// knows an empty queue means "done" rather than "not yet".
    private var queueClosed = false
    private var queueClient: JarvisAPIClient?
    private var onQueueFinished: (() -> Void)?
    private var onQueueFailed: ((Error, Bool) -> Void)?
    /// Resumed by `enqueue` and by `endQueue`, so the feeder can wait for the
    /// next sentence without polling.
    private var arrival: CheckedContinuation<Void, Never>?

    private struct Frame: Decodable {
        let type: String
        let sample_rate: Int?
        let format: String?
        let data: String?
    }

    enum PlaybackError: Error {
        case unavailable, invalidStream
    }

    init(engine: AVAudioEngine = AVAudioEngine()) {
        self.engine = engine
        engine.attach(player)
        engine.attach(timePitch)
        timePitch.rate = Float(playbackSpeed.rawValue)
        timePitch.pitch = 0
        engine.connect(player, to: timePitch, format: format)
        engine.connect(timePitch, to: engine.mainMixerNode, format: format)
    }

    func stop() {
        generation = UUID()
        feeder?.cancel()
        feeder = nil
        waiting = []
        queueClosed = false
        queueClient = nil
        onQueueFinished = nil
        onQueueFailed = nil
        onQueueDrained = nil
        resumeArrival()
        player.stop()
        engine.stop()
        #if os(iOS)
        if managesAudioSession {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
        #endif
    }

    // MARK: - one-shot

    /// Speaks one piece of text on its own. Used for anything that is not a
    /// streamed answer — a spoken notification, the voice test in settings.
    func stream(text: String, client: JarvisAPIClient, finished: @escaping () -> Void) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            var settled = false
            beginQueue(client: client, finished: finished) { error, _ in
                guard !settled else { return }
                settled = true
                continuation.resume(throwing: error)
            }
            // The queue reports its own end through `finished`; this caller only
            // waits for the download to succeed or fail, exactly as before.
            onQueueDrained = {
                guard !settled else { return }
                settled = true
                continuation.resume()
            }
            enqueue(text)
            endQueue()
        }
    }

    /// Fires when the last sentence has been fetched — not when it has been
    /// heard. `onQueueFinished` is the one that means heard.
    private var onQueueDrained: (() -> Void)?

    // MARK: - queue

    /// Opens a run of sentences. The engine is left alone: a queue that starts
    /// while the previous one is still draining would otherwise clip it.
    func beginQueue(client: JarvisAPIClient,
                    finished: @escaping () -> Void,
                    failed: ((Error, Bool) -> Void)?) {
        stop()
        generation = UUID()
        hasScheduledAudio = false
        waiting = []
        queueClosed = false
        queueClient = client
        onQueueFinished = finished
        onQueueFailed = failed
        startFeeder()
    }

    /// Adds one sentence. Safe to call while earlier sentences are still
    /// playing — that overlap is the entire point.
    func enqueue(_ text: String) {
        guard feeder != nil, !text.isEmpty else { return }
        waiting.append(text)
        resumeArrival()
    }

    /// No more sentences. The finished callback fires once the last sample has
    /// actually left the speaker.
    func endQueue() {
        guard feeder != nil else { return }
        queueClosed = true
        resumeArrival()
    }

    private func resumeArrival() {
        let waiter = arrival
        arrival = nil
        waiter?.resume()
    }

    private func startFeeder() {
        let id = generation
        feeder = Task { [weak self] in
            guard let self else { return }
            do {
                while true {
                    try Task.checkCancellation()
                    guard self.generation == id else { return }
                    if self.waiting.isEmpty {
                        if self.queueClosed { break }
                        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                            // Re-check under the actor: `endQueue` may have run
                            // between the emptiness test and this suspension,
                            // and a continuation nobody resumes hangs the queue.
                            if !self.waiting.isEmpty || self.queueClosed {
                                continuation.resume()
                            } else {
                                self.arrival = continuation
                            }
                        }
                        continue
                    }
                    let sentence = self.waiting.removeFirst()
                    try await self.fetchAndSchedule(sentence, id: id)
                }
                self.finishPlayback(id: id)
            } catch is CancellationError {
                return
            } catch {
                guard self.generation == id else { return }
                let started = self.hasScheduledAudio
                self.feeder = nil
                self.onQueueFailed?(error, started)
            }
        }
    }

    /// Downloads one sentence and hands its buffers straight to the player.
    private func fetchAndSchedule(_ text: String, id: UUID) async throws {
        guard let client = queueClient else { throw PlaybackError.unavailable }
        for textChunk in SpeechText.chunks(text) {
            try Task.checkCancellation()
            guard generation == id else { throw CancellationError() }
            let (bytes, response) = try await URLSession.shared.bytes(for: try client.speechRequest(text: textChunk))
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  http.value(forHTTPHeaderField: "Content-Type")?.contains("application/x-ndjson") == true else {
                throw PlaybackError.unavailable
            }
            var completed = false
            for try await line in bytes.lines {
                try Task.checkCancellation()
                guard generation == id else { throw CancellationError() }
                guard line.utf8.count < 800_000 else { throw PlaybackError.invalidStream }
                let frame = try JSONDecoder().decode(Frame.self, from: Data(line.utf8))
                switch frame.type {
                case "audio":
                    guard !completed, frame.sample_rate == 24_000, frame.format == "pcm_s16le",
                          let encoded = frame.data, let data = Data(base64Encoded: encoded),
                          !data.isEmpty, data.count % 2 == 0, data.count <= 512_000,
                          let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(data.count / 2)),
                          let channel = buffer.floatChannelData?[0] else { throw PlaybackError.invalidStream }
                    buffer.frameLength = buffer.frameCapacity
                    data.withUnsafeBytes { raw in
                        let input = raw.bindMemory(to: UInt8.self)
                        for index in 0..<Int(buffer.frameLength) {
                            let bits = UInt16(input[index * 2]) | (UInt16(input[index * 2 + 1]) << 8)
                            channel[index] = Float(Int16(bitPattern: bits)) / 32768
                        }
                    }
                    startEngineIfNeeded()
                    hasScheduledAudio = true
                    player.scheduleBuffer(buffer, completionHandler: nil)
                case "done":
                    completed = true
                default:
                    throw PlaybackError.invalidStream
                }
            }
            guard completed else { throw PlaybackError.invalidStream }
        }
    }

    private func startEngineIfNeeded() {
        guard !engine.isRunning else { return }
        #if os(iOS)
        if managesAudioSession {
            let session = AVAudioSession.sharedInstance()
            try? session.setCategory(.playback, mode: .spokenAudio, options: .duckOthers)
            try? session.setActive(true)
        }
        #endif
        engine.prepare()
        try? engine.start()
        player.play()
    }

    /// A single silent frame after the last sentence, so `dataPlayedBack` marks
    /// the true end of the answer rather than the end of a download.
    private func finishPlayback(id: UUID) {
        feeder = nil
        guard hasScheduledAudio, generation == id,
              let tail = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 1) else {
            onQueueFailed?(PlaybackError.invalidStream, hasScheduledAudio)
            return
        }
        onQueueDrained?()
        onQueueDrained = nil
        tail.frameLength = 1
        tail.floatChannelData?[0][0] = 0
        let finished = onQueueFinished
        player.scheduleBuffer(tail, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.generation == id else { return }
                self.stop()
                finished?()
            }
        }
    }
}
