import Foundation

/// The app clock is intentionally monotone. These values are only compared
/// with other app values; they are never combined with bridge timestamps.
enum TimingClock {
    static func nowMilliseconds() -> Double {
        Double(DispatchTime.now().uptimeNanoseconds) / 1_000_000
    }
}

enum TimingInputEvent {
    case speechEnd(Double)
    case endpointFired(Double)
}

struct TimingOutputEvent {
    let runID: String
    let event: String
    let t_ms: Double
    let seq: Int?
}

struct TimingEvent: Codable, Equatable {
    let event: String
    let t_ms: Double
    let seq: Int?

    init(event: String, t_ms: Double, seq: Int? = nil) {
        self.event = event
        self.t_ms = t_ms
        self.seq = seq
    }
}

/// Exact body accepted by POST /timing. It deliberately has no text field.
struct TimingPayload: Codable, Equatable {
    let client_run_id: String
    let events: [TimingEvent]
}

enum TimingDelivery: Equatable {
    case initial(TimingPayload)
    case followup(TimingPayload)
}

/// Keeps the microphone-side points until AppModel has made the correlation ID
/// for their following request. The class is lock-protected so an audio callback
/// can never delay a request or playback path.
final class TimingEventCollector {
    private static let maximumEvents = 64
    private static let maximumPendingEndpointAgeMilliseconds = 5_000.0
    private static let firstOnlyEvents: Set<String> = [
        "speech_end", "endpoint_fired", "request_sent", "first_text_frame",
        "first_sentence_enqueued", "playback_started", "bargein_detected", "audio_stopped"
    ]

    private struct Run {
        var events: [TimingEvent]
        var initialSent = false
        var sentCount = 0
    }

    private let lock = NSLock()
    private var enabled = false
    private var pendingSpeechEnd: TimingEvent?
    private var pendingEndpoint: TimingEvent?
    private var runs: [String: Run] = [:]

    func setEnabled(_ enabled: Bool) {
        lock.lock()
        self.enabled = enabled
        if !enabled {
            pendingSpeechEnd = nil
            pendingEndpoint = nil
            runs.removeAll()
        }
        lock.unlock()
    }

    /// The last transcript growth is the point from which the endpoint timer
    /// runs, so replacing the previous value is intentional.
    func capture(_ input: TimingInputEvent) {
        lock.lock()
        defer { lock.unlock() }
        guard enabled else { return }
        switch input {
        case .speechEnd(let t):
            // A new transcript growth after an endpoint belongs to the next
            // utterance. Keep its speech end, but never pair it with the old
            // endpoint when a later request begins.
            if pendingEndpoint != nil {
                pendingEndpoint = nil
            }
            pendingSpeechEnd = TimingEvent(event: "speech_end", t_ms: t)
        case .endpointFired(let t):
            pendingEndpoint = TimingEvent(event: "endpoint_fired", t_ms: t)
        }
    }

    /// Assigns buffered microphone points to the next client run, exactly once.
    func beginRun(_ id: String, t_ms: Double = TimingClock.nowMilliseconds()) {
        lock.lock()
        defer { lock.unlock() }
        guard enabled, runs[id] == nil else { return }
        var events: [TimingEvent] = []
        if let pendingEndpoint,
           let pendingSpeechEnd,
           pendingSpeechEnd.t_ms <= pendingEndpoint.t_ms,
           t_ms - pendingEndpoint.t_ms >= 0,
           t_ms - pendingEndpoint.t_ms <= Self.maximumPendingEndpointAgeMilliseconds {
            events.append(pendingSpeechEnd)
            events.append(pendingEndpoint)
        }
        pendingSpeechEnd = nil
        pendingEndpoint = nil
        runs[id] = Run(events: events)
    }

    /// Adds an app event. At most one of every standard measurement point is
    /// retained per run and the body cannot exceed the bridge's limit of 64.
    func record(runID: String, event: String, t_ms: Double = TimingClock.nowMilliseconds(), seq: Int? = nil) -> TimingDelivery? {
        lock.lock()
        defer { lock.unlock() }
        guard enabled, var run = runs[runID], run.events.count < Self.maximumEvents else { return nil }
        if Self.firstOnlyEvents.contains(event), run.events.contains(where: { $0.event == event }) {
            return nil
        }
        run.events.append(TimingEvent(event: event, t_ms: t_ms, seq: seq))
        let delivery: TimingDelivery?
        if event == "playback_started", !run.initialSent {
            run.initialSent = true
            run.sentCount = run.events.count
            delivery = .initial(TimingPayload(client_run_id: runID, events: run.events))
        } else if event == "audio_stopped", run.initialSent, run.sentCount < run.events.count {
            let unsent = Array(run.events.dropFirst(run.sentCount))
            run.sentCount = run.events.count
            delivery = .followup(TimingPayload(client_run_id: runID, events: unsent))
        } else {
            delivery = nil
        }
        runs[runID] = run
        return delivery
    }

    /// A textless or failed answer has no playback point. Send its collected
    /// events at the turn end instead; an answer expected to speak waits for
    /// playback_started so the initial package contains that measured point.
    func finishRun(_ id: String, expectsPlayback: Bool) -> TimingDelivery? {
        lock.lock()
        defer { lock.unlock() }
        guard enabled, var run = runs[id], !run.initialSent, !expectsPlayback,
              !run.events.isEmpty else { return nil }
        run.initialSent = true
        run.sentCount = run.events.count
        runs[id] = run
        return .initial(TimingPayload(client_run_id: id, events: run.events))
    }
}
