import Foundation

enum SpeechText {
    /// A spoken URL is unbearable — "h t t p s doppelpunkt schrägstrich…". The
    /// app shows links as attachments instead, so speech drops them and keeps
    /// only a markdown link's visible words.
    static func withoutLinks(_ text: String) -> String {
        var output = text.replacingOccurrences(
            of: #"!\[[^\]\n]*\]\((?:https?://)[^\s)]+\)"#,
            with: "", options: .regularExpression)
        output = output.replacingOccurrences(
            of: #"\[([^\]\n]*)\]\((?:https?://)[^\s)]+\)"#,
            with: "$1", options: .regularExpression)
        output = output.replacingOccurrences(
            of: #"\b(?:https?://|www\.)\S+"#,
            with: "", options: .regularExpression)
        // Collapse the gaps the removals leave behind.
        output = output.replacingOccurrences(of: #"[ \t]{2,}"#, with: " ", options: .regularExpression)
        return output.replacingOccurrences(of: #" +([.,;:!?])"#, with: "$1", options: .regularExpression)
    }

    static func chunks(_ text: String, limit: Int = 550) -> [String] {
        precondition(limit > 0)
        var remaining = withoutLinks(text).trimmingCharacters(in: .whitespacesAndNewlines)
        var result: [String] = []
        while !remaining.isEmpty {
            if remaining.unicodeScalars.count <= limit { result.append(remaining); break }
            // Python's endpoint limit counts Unicode scalars, not Swift graphemes.
            let hardEnd = remaining.unicodeScalars.index(remaining.unicodeScalars.startIndex, offsetBy: limit)
            let prefix = remaining[..<hardEnd]
            let end = prefix.lastIndex(where: { ".!?\n".contains($0) })
                .map { remaining.index(after: $0) }
                ?? prefix.lastIndex(where: { $0.isWhitespace }) ?? hardEnd
            result.append(String(remaining[..<end]).trimmingCharacters(in: .whitespacesAndNewlines))
            remaining = String(remaining[end...]).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return result.filter { !$0.isEmpty }
    }
}
