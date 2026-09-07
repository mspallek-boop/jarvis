import AVFoundation
import Foundation

/// One local preference for streamed audio and the system voice on Mac/iPhone.
enum SpeechPlaybackSpeed: Double, CaseIterable, Identifiable {
    case slow = 0.75
    case normal = 1.0
    case fast = 1.25
    case veryFast = 1.5

    static let defaultsKey = "speechPlaybackSpeed"
    var id: Double { rawValue }

    var label: String {
        switch self {
        case .slow: return "Langsam · 0,75×"
        case .normal: return "Normal · 1×"
        case .fast: return "Schnell · 1,25×"
        case .veryFast: return "Sehr schnell · 1,5×"
        }
    }

    /// Keep the existing system voice's cadence at 1×. Apple's rate scale is
    /// voice-dependent, so this is a relative setting, not a duration guarantee.
    var systemSpeechRate: Float {
        min(AVSpeechUtteranceMaximumSpeechRate,
            max(AVSpeechUtteranceMinimumSpeechRate, 0.47 * Float(rawValue)))
    }

    static func load(from defaults: UserDefaults = .standard) -> Self {
        guard let value = defaults.object(forKey: defaultsKey) as? Double,
              let speed = Self(rawValue: value) else { return .normal }
        return speed
    }

    func save(to defaults: UserDefaults = .standard) {
        defaults.set(rawValue, forKey: Self.defaultsKey)
    }
}
