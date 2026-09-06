import Foundation

/// Decides whether a partial transcript heard *while JARVIS is speaking* is the
/// user genuinely interrupting, or just noise and echo.
///
/// Kept free of AVFoundation so the judgement itself is testable. Two guards
/// matter: a single blip must not stop the answer, and JARVIS must not hear
/// itself. Echo cancellation is the real defence against the second one, but it
/// is not available on every device, so the words currently being spoken are
/// rejected here as well.
struct BargeInDetector {
    /// Shorter transcripts are a cough, a door, a clatter of dishes.
    static let minimumCharacters = 3
    /// One partial result can appear and vanish again; two mean speech.
    static let minimumUpdates = 2

    private var spokenWords: Set<String> = []
    /// Audio lags text: while sentence N+1 is handed over, the echo of sentence
    /// N is still coming back through the microphone. Keeping the previous
    /// sentence's words stops that gap from reading as the user interrupting.
    private var previousWords: Set<String> = []
    private var updates = 0
    private var lastTranscript = ""
    private(set) var hasTriggered = false

    /// The sentence JARVIS is currently reading aloud. Anything the recogniser
    /// returns that consists only of these words is treated as echo.
    mutating func nowSpeaking(_ text: String) {
        previousWords = spokenWords
        spokenWords = Set(Self.words(text))
        reset()
    }

    /// Called when the answer is finished and nothing more will be spoken.
    mutating func stoppedSpeaking() {
        spokenWords = []
        previousWords = []
        reset()
    }

    mutating func reset() {
        updates = 0
        lastTranscript = ""
        hasTriggered = false
    }

    /// Returns true exactly once, on the update that should stop the playback.
    mutating func shouldInterrupt(partial: String) -> Bool {
        guard !hasTriggered else { return false }
        let trimmed = partial.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= Self.minimumCharacters, trimmed != lastTranscript else { return false }

        let heard = Self.words(trimmed)
        guard !heard.isEmpty else { return false }
        // Every word already coming out of the speaker: this is the echo of our
        // own voice, not the user. Do not count it as an update either.
        guard !heard.allSatisfy({ spokenWords.contains($0) || previousWords.contains($0) })
        else { return false }

        lastTranscript = trimmed
        updates += 1
        guard updates >= Self.minimumUpdates else { return false }
        hasTriggered = true
        return true
    }

    private static func words(_ text: String) -> [String] {
        text.lowercased()
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
    }
}
