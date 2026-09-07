import AVFoundation
import Foundation

/// Plays authenticated PCM chunks as they arrive; never stores speech on disk.
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
        player.stop()
        engine.stop()
        #if os(iOS)
        if managesAudioSession {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
        #endif
    }

    func stream(text: String, client: JarvisAPIClient, finished: @escaping () -> Void) async throws {
        stop()
        let id = UUID()
        generation = id
        hasScheduledAudio = false
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
                    if !engine.isRunning {
                        #if os(iOS)
                        if managesAudioSession {
                            let session = AVAudioSession.sharedInstance()
                            try session.setCategory(.playback, mode: .spokenAudio, options: .duckOthers)
                            try session.setActive(true)
                        }
                        #endif
                        engine.prepare()
                        try engine.start()
                        player.play()
                    }
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
        guard hasScheduledAudio, generation == id,
              let tail = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 1) else {
            throw PlaybackError.invalidStream
        }
        tail.frameLength = 1
        tail.floatChannelData?[0][0] = 0
        player.scheduleBuffer(tail, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.generation == id else { return }
                self.stop()
                finished()
            }
        }
    }

}
