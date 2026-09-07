import AVFoundation
import Foundation

// Keep test preferences in memory; never write app or system preferences.
private final class MemoryDefaults: UserDefaults {
    private var values: [String: Any] = [:]
    override func object(forKey defaultName: String) -> Any? { values[defaultName] }
    override func set(_ value: Any?, forKey defaultName: String) { values[defaultName] = value }
}

@main
struct SpeechPlaybackSpeedTests {
    @MainActor
    static func main() throws {
        let defaults = MemoryDefaults(suiteName: "JARVIS.SpeechPlaybackSpeedTests")!
        precondition(SpeechPlaybackSpeed.load(from: defaults) == .normal)
        for speed in SpeechPlaybackSpeed.allCases {
            speed.save(to: defaults)
            precondition(defaults.object(forKey: SpeechPlaybackSpeed.defaultsKey) as? Double == speed.rawValue)
            precondition(SpeechPlaybackSpeed.load(from: defaults) == speed)
            precondition(!speed.label.isEmpty)
            precondition((AVSpeechUtteranceMinimumSpeechRate...AVSpeechUtteranceMaximumSpeechRate)
                .contains(speed.systemSpeechRate))
        }
        for invalid: Any in [0.0, -1.0, 99.0, 1.1, Double.nan, Double.infinity, "fast"] {
            defaults.set(invalid, forKey: SpeechPlaybackSpeed.defaultsKey)
            precondition(SpeechPlaybackSpeed.load(from: defaults) == .normal)
        }
        precondition(SpeechPlaybackSpeed.normal.systemSpeechRate == 0.47)
        precondition(SpeechPlaybackSpeed.slow.systemSpeechRate < SpeechPlaybackSpeed.normal.systemSpeechRate)
        precondition(SpeechPlaybackSpeed.fast.systemSpeechRate > SpeechPlaybackSpeed.normal.systemSpeechRate)
        precondition(SpeechPlaybackSpeed.veryFast.systemSpeechRate > SpeechPlaybackSpeed.fast.systemSpeechRate)
        print("Speech speed: default, 4 in-memory persistence round trips, 7 invalid values and system rates passed")
        if CommandLine.arguments.contains("--skip-audio") {
            print("SKIPPED: offline audio duration/pitch, live changes and stop (--skip-audio)")
            return
        }

        // Render the production player's graph without speakers or a server:
        // changing metadata alone must not pass these duration/pitch checks.
        for speed in SpeechPlaybackSpeed.allCases {
            let duration = try renderedDuration(speed: speed)
            precondition(abs(duration - 2 / speed.rawValue) < 0.15,
                         "Wrong rendered duration at \(speed): \(duration)")
        }
        let changedDuration = try renderedDuration(speed: .normal, changeWhilePlaying: true)
        precondition(changedDuration > 1.5 && changedDuration < 1.85,
                     "Live speed change did not affect scheduled audio: \(changedDuration)")
        print("Speech speed: defaults, persistence, invalid values, system rates, PCM duration/pitch, live changes and stop passed")
    }

    @MainActor
    private static func renderedDuration(speed: SpeechPlaybackSpeed,
                                         changeWhilePlaying: Bool = false) throws -> Double {
        let engine = AVAudioEngine()
        let speech = NeuralSpeechPlayer(engine: engine)
        speech.managesAudioSession = false
        speech.playbackSpeed = speed
        let player = engine.attachedNodes.compactMap { $0 as? AVAudioPlayerNode }.first!
        let effect = engine.attachedNodes.compactMap { $0 as? AVAudioUnitTimePitch }.first!
        precondition(effect.rate == Float(speed.rawValue) && effect.pitch == 0)
        let format = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1)!
        try engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: 512)
        let input = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 72_000)!
        input.frameLength = input.frameCapacity
        for index in 0..<Int(input.frameLength) {
            input.floatChannelData![0][index] = index < 48_000
                ? Float(0.5 * sin(2 * Double.pi * 440 * Double(index) / 24_000)) : 0
        }
        player.scheduleBuffer(input)
        try engine.start()
        player.play()
        let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 512)!
        var samples: [Float] = []
        var changed = false
        var attempts = 0
        while samples.count < 96_000 {
            if changeWhilePlaying && !changed && samples.count >= 24_000 {
                speech.playbackSpeed = .veryFast
                precondition(engine.isRunning && player.isPlaying)
                changed = true
            }
            let status = try engine.renderOffline(512, to: output)
            attempts += 1
            precondition(attempts < 1000, "Offline renderer stalled")
            switch status {
            case .success:
                samples.append(contentsOf: UnsafeBufferPointer(start: output.floatChannelData![0],
                                                               count: Int(output.frameLength)))
            case .cannotDoInCurrentContext: continue
            default: preconditionFailure("Offline rendering failed: \(status)")
            }
        }
        let first = samples.firstIndex { abs($0) > 0.01 }!
        let last = samples.lastIndex { abs($0) > 0.01 }!
        // Frequency over a stable middle window stays near 440 Hz at every rate.
        let window = Array(samples[12_000..<18_000])
        let crossings = zip(window, window.dropFirst()).filter { $0 < 0 && $1 >= 0 }.count
        precondition(abs(Double(crossings) / 0.25 - 440) < 12, "Playback changed pitch")
        speech.stop()
        precondition(!engine.isRunning && !player.isPlaying)
        precondition(speech.playbackSpeed == (changeWhilePlaying ? .veryFast : speed))
        return Double(last - first) / 24_000
    }
}
