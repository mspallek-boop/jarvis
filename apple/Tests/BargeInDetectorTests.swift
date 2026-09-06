import Foundation

@main struct BargeInTests {
    static func main() {
        // Two real updates interrupt, and only the first one reports it.
        var normal = BargeInDetector()
        normal.nowSpeaking("Ihr Termin läuft noch bis zwanzig Uhr.")
        precondition(normal.shouldInterrupt(partial: "warte") == false)
        precondition(normal.shouldInterrupt(partial: "warte mal") == true)
        precondition(normal.shouldInterrupt(partial: "warte mal kurz") == false)
        precondition(normal.hasTriggered)

        // A single blip is not enough.
        var blip = BargeInDetector()
        blip.nowSpeaking("Guten Abend.")
        precondition(blip.shouldInterrupt(partial: "hm") == false)
        precondition(blip.shouldInterrupt(partial: "hm") == false)
        precondition(blip.hasTriggered == false)

        // Too short stays silent however often it repeats.
        var short = BargeInDetector()
        short.nowSpeaking("Guten Abend.")
        for _ in 0..<5 { precondition(short.shouldInterrupt(partial: "ah") == false) }

        // Our own voice coming back through the microphone must never trigger.
        var echo = BargeInDetector()
        echo.nowSpeaking("Ihr Termin im Haus des Meeres läuft noch bis zwanzig Uhr.")
        precondition(echo.shouldInterrupt(partial: "Ihr Termin") == false)
        precondition(echo.shouldInterrupt(partial: "Ihr Termin im Haus") == false)
        precondition(echo.shouldInterrupt(partial: "Ihr Termin im Haus des Meeres") == false)
        precondition(echo.hasTriggered == false)
        // …but real words mixed into the echo do.
        precondition(echo.shouldInterrupt(partial: "Ihr Termin stopp") == false)
        precondition(echo.shouldInterrupt(partial: "Ihr Termin stopp bitte") == true)

        // Punctuation and case must not make echo look like new speech.
        var punctuation = BargeInDetector()
        punctuation.nowSpeaking("Soll ich die Erinnerungen durchgehen?")
        precondition(punctuation.shouldInterrupt(partial: "soll ich") == false)
        precondition(punctuation.shouldInterrupt(partial: "Soll ich die") == false)
        precondition(punctuation.hasTriggered == false)

        // A new sentence clears the previous state.
        var reused = BargeInDetector()
        reused.nowSpeaking("Erster Satz.")
        precondition(reused.shouldInterrupt(partial: "nein danke") == false)
        precondition(reused.shouldInterrupt(partial: "nein danke sehr") == true)
        reused.nowSpeaking("Zweiter Satz.")
        precondition(reused.hasTriggered == false)
        precondition(reused.shouldInterrupt(partial: "moment") == false)
        precondition(reused.shouldInterrupt(partial: "moment bitte") == true)

        // Whitespace-only and empty partials are ignored entirely.
        var empty = BargeInDetector()
        empty.nowSpeaking("Guten Abend.")
        precondition(empty.shouldInterrupt(partial: "") == false)
        precondition(empty.shouldInterrupt(partial: "    ") == false)
        precondition(empty.shouldInterrupt(partial: "!!!") == false)

        // The echo of the sentence just finished still arrives while the next
        // one starts. It must not read as the user interrupting.
        var gap = BargeInDetector()
        gap.nowSpeaking("Ihr Termin läuft bis zwanzig Uhr.")
        gap.nowSpeaking("Ansonsten ist der Abend frei.")
        precondition(gap.shouldInterrupt(partial: "Ihr Termin läuft") == false)
        precondition(gap.shouldInterrupt(partial: "Ihr Termin läuft bis zwanzig") == false)
        precondition(gap.hasTriggered == false)
        // Real speech during that same gap still gets through.
        precondition(gap.shouldInterrupt(partial: "nein warte") == false)
        precondition(gap.shouldInterrupt(partial: "nein warte doch") == true)

        // Once the answer is over, its words are no longer excused.
        var after = BargeInDetector()
        after.nowSpeaking("Der Abend ist frei.")
        after.stoppedSpeaking()
        precondition(after.shouldInterrupt(partial: "der Abend") == false)
        precondition(after.shouldInterrupt(partial: "der Abend ist") == true)

        print("Barge-in: Auslösung, Blip, Kürze, Echo, Interpunktion, Reset, Satzlücke und Leereingaben bestanden")
    }
}
