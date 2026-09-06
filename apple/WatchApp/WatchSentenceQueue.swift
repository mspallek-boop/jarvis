import Foundation

/// WatchConnectivity can deliver the final context before individual messages.
/// Sequence numbers prevent duplicate speech and let the final list fill gaps.
struct WatchSentenceQueue {
    private var pending: [Int: String] = [:]
    private(set) var deliveredCount = 0

    mutating func receive(_ sentence: String, index: Int) -> [String] {
        guard index >= deliveredCount, index < 1000, !sentence.isEmpty,
              sentence.unicodeScalars.count <= 600 else { return [] }
        if pending[index] == nil { pending[index] = sentence }
        var ready: [String] = []
        while let next = pending.removeValue(forKey: deliveredCount) {
            ready.append(next)
            deliveredCount += 1
        }
        return ready
    }

    mutating func finish(_ sentences: [String]) -> [String] {
        guard sentences.count <= 1000 else { return [] }
        var ready: [String] = []
        for (index, sentence) in sentences.enumerated() {
            ready += receive(sentence, index: index)
        }
        return ready
    }
}
