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
