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
        // The bridge replaces every inline image with a [Bild] marker and moves
        // the picture into the attachments. On the voice stage the gallery
        // shows that picture, so the word for it is noise.
        precondition(VoiceStageText.withoutPicturePlaceholders(
            "Hier ist die Garage.\n\n[Bild]", hasPictures: true) == "Hier ist die Garage.")
        precondition(VoiceStageText.withoutPicturePlaceholders(
            "[Bild] Welches gefällt dir? [Bild]", hasPictures: true) == "Welches gefällt dir?")
        // Without a gallery the marker is the only sign a picture exists.
        precondition(VoiceStageText.withoutPicturePlaceholders(
            "Hier ist die Garage.\n\n[Bild]", hasPictures: false) == "Hier ist die Garage.\n\n[Bild]")
        // Nothing else that looks like a bracket may be eaten.
        precondition(VoiceStageText.withoutPicturePlaceholders(
            "[Bildschirm] bleibt", hasPictures: true) == "[Bildschirm] bleibt")

        // Being called by name, as the recogniser actually hears it.
        precondition(WakePhrase.after("Hey Jarvis, wie spät ist es?") == "wie spät ist es?")
        precondition(WakePhrase.after("Hey Service, mach das Licht an") == "mach das Licht an")
        // Groß- und Kleinschreibung sowie Satzzeichen überleben — der Satz geht so an das Modell.
        precondition(WakePhrase.after("Hey Jarvis: Wie spät ist es?") == "Wie spät ist es?")
        precondition(WakePhrase.after("Hey Jarvis") == "")            // Anruf ohne Auftrag
        precondition(WakePhrase.after("Wie spät ist es?") == nil)     // nicht an ihn gerichtet
        precondition(WakePhrase.after("Sag Jarvis, er soll warten") == nil)  // nur erwähnt
        precondition(WakePhrase.after("") == nil)

        print("17 answer rendering cases passed")
    }
}
