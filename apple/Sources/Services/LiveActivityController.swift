#if os(iOS)
import ActivityKit
import Foundation

/// Keeps one Live Activity per running turn alive on the lock screen and in
/// the Dynamic Island.
///
/// The app is suspended within seconds of the screen going off, so nothing it
/// does itself can keep the user informed past that point. A Live Activity is
/// the only thing that outlives the suspension, and it is why the turn no
/// longer looks like a dropped connection: the work continues on the Mac, and
/// the phone keeps showing it.
///
/// Updates are throttled. A streaming answer produces tokens far faster than
/// the system will render them, and pushing every delta gets the activity rate
/// limited and then ignored — which would leave a stale phase on the screen,
/// the exact failure this is meant to remove.
@MainActor
final class LiveActivityController {
    private var activities: [String: Activity<JarvisActivityAttributes>] = [:]
    private var lastUpdate: [String: Date] = [:]
    private var pending: [String: JarvisActivityAttributes.ContentState] = [:]
    private var flushTask: [String: Task<Void, Never>] = [:]

    /// Half a second is under the system's rate limit and still reads as live.
    private static let minimumInterval: TimeInterval = 0.5

    private var enabled: Bool {
        ActivityAuthorizationInfo().areActivitiesEnabled
    }

    /// Puts a freshly started turn on the lock screen.
    func start(runID: String, prompt: String, phase: String) {
        guard enabled, activities[runID] == nil else { return }
        let attributes = JarvisActivityAttributes(prompt: prompt)
        let state = JarvisActivityAttributes.ContentState(
            phase: phase, reply: "", isFinished: false, failure: nil)
        do {
            activities[runID] = try Activity.request(
                attributes: attributes,
                content: .init(state: state, staleDate: Date().addingTimeInterval(15 * 60)))
            lastUpdate[runID] = Date()
        } catch {
            // Denied permission or too many activities. The app is unaffected;
            // this is an extra window onto the work, never the work itself.
        }
    }

    /// Reports progress. Safe to call on every streamed token.
    func update(runID: String, phase: String, reply: String) {
        guard let activity = activities[runID] else { return }
        let state = JarvisActivityAttributes.ContentState(
            phase: phase, reply: reply, isFinished: false, failure: nil)
        let elapsed = Date().timeIntervalSince(lastUpdate[runID] ?? .distantPast)
        guard elapsed >= Self.minimumInterval else {
            // Hold the newest state and let one scheduled flush deliver it, so
            // the last token before a pause is never the one that gets dropped.
            pending[runID] = state
            scheduleFlush(runID: runID, in: Self.minimumInterval - elapsed)
            return
        }
        deliver(state, to: activity, runID: runID)
    }

    /// Ends the activity. A finished answer lingers briefly so a user who
    /// picks the phone up right then still sees the result; a failure lingers
    /// longer, because it is the one the user has to act on.
    func finish(runID: String, reply: String, failure: String? = nil) {
        guard let activity = activities[runID] else { return }
        flushTask[runID]?.cancel()
        flushTask[runID] = nil
        pending[runID] = nil
        let state = JarvisActivityAttributes.ContentState(
            phase: "Fertig", reply: reply, isFinished: true, failure: failure)
        activities[runID] = nil
        lastUpdate[runID] = nil
        Task {
            await activity.end(.init(state: state, staleDate: nil),
                               dismissalPolicy: .after(Date().addingTimeInterval(failure == nil ? 8 : 30)))
        }
    }

    /// Clears everything — used when the user signs out or the app is reset.
    func endAll() {
        for runID in activities.keys { finish(runID: runID, reply: "") }
    }

    private func scheduleFlush(runID: String, in delay: TimeInterval) {
        guard flushTask[runID] == nil else { return }
        flushTask[runID] = Task { [weak self] in
            try? await Task.sleep(for: .seconds(max(delay, 0)))
            guard !Task.isCancelled, let self else { return }
            self.flushTask[runID] = nil
            guard let state = self.pending.removeValue(forKey: runID),
                  let activity = self.activities[runID] else { return }
            self.deliver(state, to: activity, runID: runID)
        }
    }

    private func deliver(_ state: JarvisActivityAttributes.ContentState,
                         to activity: Activity<JarvisActivityAttributes>,
                         runID: String) {
        lastUpdate[runID] = Date()
        Task {
            await activity.update(.init(state: state,
                                        staleDate: Date().addingTimeInterval(15 * 60)))
        }
    }
}
#endif
