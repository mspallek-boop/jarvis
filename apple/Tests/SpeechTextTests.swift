import Foundation

@main
struct SpeechTextTests {
    static func main() {
        let examples = [
            "", "   \n  ", "Hallo, Marlon.",
            String(repeating: "Übermorgen ist ein schöner Tag. ", count: 80),
            String(repeating: "ä", count: 1700),
            String(repeating: "👨‍👩‍👦 ", count: 800),
            String(repeating: "Wort ", count: 400),
            String(repeating: "?!", count: 1000)
        ]
        for text in examples {
            let chunks = SpeechText.chunks(text)
            precondition(chunks.allSatisfy { !$0.isEmpty && $0.unicodeScalars.count <= 550 })
            let normalized: (String) -> String = { $0.filter { !$0.isWhitespace } }
            precondition(normalized(chunks.joined()) == normalized(text), "Speech content lost")
        }
        // A spoken URL is unbearable; the app shows links as attachments.
        precondition(SpeechText.withoutLinks("Siehe https://example.com/a.png hier.")
                     == "Siehe hier.")
        precondition(SpeechText.withoutLinks("Laut [Wikipedia](https://de.wikipedia.org/wiki/Katze) stimmt das.")
                     == "Laut Wikipedia stimmt das.")
        precondition(SpeechText.withoutLinks("Bild ![Katze](https://x.de/k.png) dazu.")
                     == "Bild dazu.")
        precondition(SpeechText.withoutLinks("Ohne Link bleibt alles.")
                     == "Ohne Link bleibt alles.")
        // The space the removed URL leaves behind goes with it.
        precondition(SpeechText.chunks("Schau auf https://example.com/lang/pfad .") == ["Schau auf."])

        print("12 speech chunking cases passed (content preserved, Unicode safe, request bound respected)")
    }
}
