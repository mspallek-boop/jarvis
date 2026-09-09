#if os(macOS)
import Foundation

/// The on/off switch for always-on „Hey JARVIS“.
///
/// The detector is a separate launchd process, deliberately: it never
/// transcribes, and it holds the microphone only while the app is running.
/// But "while the app is running" is still all day, and an open input stream
/// is enough to duck the Mac's output — which is why JARVIS could be left
/// listening and the user hearing nothing.
///
/// The switch is a single file whose *presence* means off. That is the whole
/// protocol: no port, no socket, no XPC, in keeping with the one-way
/// `jarvis://wake` URL the detector uses in the other direction. A file that
/// somehow gets stuck has one obvious meaning and one obvious repair.
enum WakeWordSwitch {
    static let flagURL = URL(fileURLWithPath: NSHomeDirectory())
        .appendingPathComponent(".hermes/wakeword-off")

    /// Absent file means listening, so an install that never touched this
    /// behaves exactly as it did before the switch existed.
    static var isEnabled: Bool {
        !FileManager.default.fileExists(atPath: flagURL.path)
    }

    /// True when the detector is installed at all. Without it the toggle would
    /// promise something nothing acts on.
    static var isAvailable: Bool {
        FileManager.default.fileExists(
            atPath: NSHomeDirectory() + "/.hermes/services/jarvis-wakeword.py")
    }

    @discardableResult
    static func setEnabled(_ enabled: Bool) -> Bool {
        let manager = FileManager.default
        do {
            if enabled {
                if manager.fileExists(atPath: flagURL.path) {
                    try manager.removeItem(at: flagURL)
                }
            } else {
                try manager.createDirectory(at: flagURL.deletingLastPathComponent(),
                                            withIntermediateDirectories: true)
                // The content is for a human reading it later, never parsed.
                try Data("Weckwort in den JARVIS-Einstellungen ausgeschaltet.\n".utf8)
                    .write(to: flagURL, options: .atomic)
            }
            return true
        } catch {
            return false
        }
    }
}
#endif
