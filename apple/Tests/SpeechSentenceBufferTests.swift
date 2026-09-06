import Foundation

@main struct SentenceTests {
    static func main() {
        var b = SpeechSentenceBuffer()
        precondition(b.append("Hallo") == [])
        precondition(b.append(". Wie ") == ["Hallo."])
        precondition(b.append("geht es?") == [])
        precondition(b.finish(finalText: "Hallo. Wie geht es?") == ["Wie geht es?"])
        var decimal = SpeechSentenceBuffer()
        precondition(decimal.append("Es sind 3.14 Euro. Passt das? ") == ["Es sind 3.14 Euro.", "Passt das?"])
        precondition(decimal.finish(finalText: "Es sind 3.14 Euro. Passt das?") == [])
        var abbreviation = SpeechSentenceBuffer()
        precondition(abbreviation.append("Dr. Müller hilft. Danach ") == ["Dr. Müller hilft."])
        var fallback = SpeechSentenceBuffer()
        precondition(fallback.finish(finalText: "Antwort einer alten Bridge.") == ["Antwort einer alten Bridge."])
        var corrected = SpeechSentenceBuffer()
        precondition(corrected.append("Ich suche. ") == ["Ich suche."])
        precondition(corrected.finish(finalText: "Das endgültige Ergebnis ist da.") == [])
        var spaces = SpeechSentenceBuffer()
        precondition(spaces.append("Hallo. Der Rest\n") == ["Hallo."])
        precondition(spaces.finish(finalText: "Hallo. Der Rest") == ["Der Rest"])
        var unicode = SpeechSentenceBuffer()
        precondition(unicode.append("Grüß dich 👋🏽! Schön, ") == ["Grüß dich 👋🏽!"])
        precondition(unicode.finish(finalText: "Grüß dich 👋🏽! Schön, dass du da bist.") == ["Schön, dass du da bist."])
        print("7 incremental sentence scenarios passed")
    }
}
