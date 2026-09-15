import Foundation

@main
struct TimingEventCollectorTests {
    static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
        precondition(condition(), message)
    }

    static func payload(from delivery: TimingDelivery?) -> TimingPayload {
        guard case .initial(let payload)? = delivery else { fatalError("expected initial delivery") }
        return payload
    }

    static func main() throws {
        let collector = TimingEventCollector()
        collector.setEnabled(true)

        // Input belongs to the run it causes, not to a previous run.
        collector.capture(.speechEnd(10))
        collector.capture(.speechEnd(12))
        collector.capture(.endpointFired(20))
        collector.beginRun("run-1", t_ms: 20)
        expect(collector.record(runID: "run-1", event: "request_sent", t_ms: 25) == nil, "request is not delivered early")
        expect(collector.record(runID: "run-1", event: "first_text_frame", t_ms: 30) == nil, "text is not delivered early")
        expect(collector.record(runID: "run-1", event: "first_text_frame", t_ms: 31) == nil, "first text only once")
        expect(collector.record(runID: "run-1", event: "first_sentence_enqueued", t_ms: 35, seq: 0) == nil, "enqueue is not delivered early")
        let first = payload(from: collector.record(runID: "run-1", event: "playback_started", t_ms: 40, seq: 0))
        expect(first.client_run_id == "run-1", "run id")
        expect(first.events.map(\.event) == ["speech_end", "endpoint_fired", "request_sent", "first_text_frame", "first_sentence_enqueued", "playback_started"], "event order and input mapping")
        expect(first.events.first?.t_ms == 12, "last transcript growth wins")
        expect(collector.record(runID: "run-1", event: "playback_started", t_ms: 41, seq: 0) == nil, "playback once per run")
        expect(collector.finishRun("run-1", expectsPlayback: false) == nil, "initial package once per run")

        let encoded = try JSONEncoder().encode(first)
        let object = try JSONSerialization.jsonObject(with: encoded) as! [String: Any]
        expect(Set(object.keys) == ["client_run_id", "events"], "contract has no additional fields")
        let events = object["events"] as! [[String: Any]]
        expect(events.count == 6 && events.allSatisfy { $0["event"] is String && $0["t_ms"] is NSNumber }, "contract event shape")
        expect(!String(data: encoded, encoding: .utf8)!.contains("Hallo"), "payload contains no text")

        let typed = TimingEventCollector()
        typed.setEnabled(true)
        typed.beginRun("typed", t_ms: 100)
        _ = typed.record(runID: "typed", event: "request_sent", t_ms: 100)
        let typedPayload = payload(from: typed.finishRun("typed", expectsPlayback: false))
        expect(typedPayload.events.map(\.event) == ["request_sent"], "typed turns have no microphone events")

        let stale = TimingEventCollector()
        stale.setEnabled(true)
        stale.capture(.speechEnd(10))
        stale.capture(.endpointFired(20))
        stale.beginRun("stale", t_ms: 5_021)
        _ = stale.record(runID: "stale", event: "request_sent", t_ms: 5_021)
        let stalePayload = payload(from: stale.finishRun("stale", expectsPlayback: false))
        expect(stalePayload.events.map(\.event) == ["request_sent"], "stale endpoint is discarded")

        let nextUtterance = TimingEventCollector()
        nextUtterance.setEnabled(true)
        nextUtterance.capture(.speechEnd(10))
        nextUtterance.capture(.endpointFired(20))
        nextUtterance.capture(.speechEnd(30))
        nextUtterance.capture(.endpointFired(40))
        nextUtterance.beginRun("next-utterance", t_ms: 40)
        _ = nextUtterance.record(runID: "next-utterance", event: "request_sent", t_ms: 41)
        let nextPayload = payload(from: nextUtterance.finishRun("next-utterance", expectsPlayback: false))
        expect(nextPayload.events.map(\.event) == ["speech_end", "endpoint_fired", "request_sent"], "new speech end starts the next utterance")
        expect(nextPayload.events[0].t_ms == 30 && nextPayload.events[1].t_ms == 40, "old endpoint is not attached")

        let bounded = TimingEventCollector()
        bounded.setEnabled(true)
        bounded.beginRun("run-2")
        for i in 0..<70 { _ = bounded.record(runID: "run-2", event: "extra_\(i)", t_ms: Double(i)) }
        let capped = payload(from: bounded.finishRun("run-2", expectsPlayback: false))
        expect(capped.events.count == 64, "maximum 64 events")
        print("TimingEventCollectorTests: PASS")
    }
}
