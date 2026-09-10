import Foundation

/// Research sources remain tappable in voice mode and the conversation history.
enum AnswerText {
    static func formatted(_ text: String) -> AttributedString {
        var result = (try? AttributedString(markdown: text, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
        // Agent output may contain links; only explicit web navigation is allowed.
        for run in result.runs {
            if let link = run.link,
               !["https", "http"].contains(link.scheme?.lowercased() ?? "") {
                result[run.range].link = nil
            }
        }
        // Hermes also returns plain source URLs, not just Markdown links.
        let plain = String(result.characters)
        if let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) {
            for match in detector.matches(in: plain, range: NSRange(plain.startIndex..., in: plain)) {
                guard let url = match.url, ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
                      let stringRange = Range(match.range, in: plain),
                      let start = AttributedString.Index(stringRange.lowerBound, within: result),
                      let end = AttributedString.Index(stringRange.upperBound, within: result),
                      !result[start..<end].runs.contains(where: { $0.link != nil }) else { continue }
                result[start..<end].link = url
            }
        }
        return result
    }
}

/// What the voice stage does with the markers the bridge leaves behind.
enum VoiceStageText {
    /// The bridge swaps every inline image for a `[Bild]` marker and moves the
    /// picture into the attachments. In the message list that marker sits next
    /// to the picture and reads fine. On the voice stage the text is centred
    /// and alone, so once the gallery is showing the same picture, the marker
    /// is a word for something already on screen.
    static func withoutPicturePlaceholders(_ text: String, hasPictures: Bool) -> String {
        guard hasPictures else { return text }
        let stripped = text.replacingOccurrences(
            of: #"\[Bild\]"#, with: "", options: .regularExpression)
        return stripped
            .replacingOccurrences(of: #"[ \t]{2,}"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
