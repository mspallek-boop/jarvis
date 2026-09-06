import Foundation

/// Wait for a sentence boundary, not the end of the entire agent turn.
struct SpeechSentenceBuffer {
    private var received = ""
    private var pending = ""
    private var hasEmitted = false

    mutating func append(_ delta: String) -> [String] {
        received += delta
        pending += delta
        var output: [String] = []
        let expression = try! NSRegularExpression(pattern: "[.!?](?:[\"”»])?\\s+")
        while let boundary = expression.matches(in: pending, range: NSRange(pending.startIndex..., in: pending)).first(where: { match in
            let prefix = (pending as NSString).substring(to: match.range.location + 1)
            return prefix.range(of: #"\b(?:Dr|Prof|bzw|ca|usw|z|B|d|h)\.$"#, options: .regularExpression) == nil
        }) {
            let end = NSMaxRange(boundary.range)
            let sentence = (pending as NSString).substring(to: end)
            pending = (pending as NSString).substring(from: end)
            output += SpeechText.chunks(sentence)
        }
        hasEmitted = hasEmitted || !output.isEmpty
        return output
    }

    mutating func finish(finalText: String) -> [String] {
        if finalText.trimmingCharacters(in: .whitespacesAndNewlines) == received.trimmingCharacters(in: .whitespacesAndNewlines) {
            // Bridge normalizes the final response, while deltas retain spaces.
        } else if finalText.hasPrefix(received) {
            pending += finalText.dropFirst(received.count)
        } else if !hasEmitted {
            pending = finalText
        } else if finalText != received {
            // Hermes may replace streamed wording with a final answer. Keep the
            // authoritative text on screen; do not repeat or splice new wording.
            pending = ""
        }
        let result = SpeechText.chunks(pending)
        pending = ""
        return result
    }
}
