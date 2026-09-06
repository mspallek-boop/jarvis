import Foundation

@main struct WatchQueueTests {
    static func main() {
        var queue = WatchSentenceQueue()
        precondition(queue.receive("Zweiter Satz.", index: 1) == [])
        precondition(queue.receive("Erster Satz.", index: 0) == ["Erster Satz.", "Zweiter Satz."])
        precondition(queue.receive("Erster Satz.", index: 0) == [])
        precondition(queue.finish(["Erster Satz.", "Zweiter Satz.", "Dritter Satz."]) == ["Dritter Satz."])
        precondition(queue.finish(["Erster Satz.", "Zweiter Satz.", "Dritter Satz."]) == [])
        var finalFirst = WatchSentenceQueue()
        precondition(finalFirst.finish(["Hallo.", "Wie geht es?"]) == ["Hallo.", "Wie geht es?"])
        precondition(finalFirst.receive("Hallo.", index: 0) == [])
        precondition(finalFirst.receive("Ungültig", index: -1) == [])
        precondition(finalFirst.receive("Ungültig", index: 1000) == [])
        precondition(finalFirst.receive(String(repeating: "x", count: 601), index: 2) == [])
        print("Watch ordering, deduplication, final recovery and bounds passed")
    }
}
