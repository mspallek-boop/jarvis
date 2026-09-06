import Foundation

@main struct AnswerTextTests {
    static func main() {
        let linked = AnswerText.formatted("Quelle: [Apple](https://apple.com)\nZweite Zeile")
        precondition(String(linked.characters) == "Quelle: Apple\nZweite Zeile")
        precondition(linked.runs.contains { $0.link?.host == "apple.com" })
        for target in ["file:///etc/passwd", "javascript:alert", "uber://action", "data:text/plain,hi"] {
            precondition(!AnswerText.formatted("[Link](\(target))").runs.contains { $0.link != nil })
        }
        let plain = AnswerText.formatted("Quelle: https://github.com/eadmin2/jarvis_ai")
        precondition(plain.runs.contains { $0.link?.host == "github.com" })
        print("6 answer rendering cases passed")
    }
}
