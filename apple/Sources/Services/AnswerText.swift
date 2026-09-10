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


/// Being called by name, as heard rather than as spelled.
///
/// This is as close to a system wake word as a third-party app gets on iOS:
/// only Siri may listen while an app is not running. So the phrase is matched
/// in what the recogniser returned, and the recogniser mangles a name it does
/// not know — "Jarvis" comes back from German audio as any of these. The test
/// is deliberately loose: a false positive costs one ignored sentence, a false
/// negative means he never answers at all.
enum WakePhrase {
    static let variants = [
        "hey jarvis", "hey järvis", "hey dscharvis", "hey charvis",
        "hey service", "hey jervis", "hey jarwis", "hi jarvis", "ok jarvis",
    ]

    /// The sentence with the name taken off the front, **as it was said**.
    ///
    /// Only the matching is case- and punctuation-blind; what comes back is
    /// the original slice. An earlier version returned its own normalised
    /// form, which meant the model was asked to "mach das licht an" — the
    /// sentence stripped of the capitals German needs and of the punctuation
    /// that tells a question from an order.
    ///
    /// Empty means he was called and nothing else was said — a summons, not a
    /// task. Nil means the sentence was not addressed to him.
    static func after(_ text: String) -> String? {
        let alternatives = variants
            .map { $0.replacingOccurrences(of: " ", with: "[\\s,]+") }
            .joined(separator: "|")
        guard let expression = try? NSRegularExpression(
            pattern: "^[\\s]*(?:\(alternatives))\\b[\\s,.:;!?-]*",
            options: [.caseInsensitive]) else { return nil }
        let whole = NSRange(text.startIndex..., in: text)
        guard let match = expression.firstMatch(in: text, options: [.anchored], range: whole),
              match.range.length > 0,
              let consumed = Range(match.range, in: text) else { return nil }
        return String(text[consumed.upperBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
