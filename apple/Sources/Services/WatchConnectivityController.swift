#if os(iOS)
import Foundation
import UIKit
import WatchConnectivity

final class WatchConnectivityController: NSObject, WCSessionDelegate {
    var messageHandler: ((String, String) async -> String)?
    private var sentencesByRequest: [String: [String]] = [:]
    /// WatchConnectivity wakes the phone only briefly. A Hermes turn takes far
    /// longer than that, and a suspended app never sends the answer back — the
    /// watch then waits for its 430s timeout while the message sits answered in
    /// Hermes. This assertion buys the time to finish and reply.
    private var backgroundTasks: [String: UIBackgroundTaskIdentifier] = [:]

    @MainActor
    private func beginBackgroundWork(id: String) {
        endBackgroundWork(id: id)
        let task = UIApplication.shared.beginBackgroundTask(withName: "jarvis.watch.\(id)") { [weak self] in
            // iOS is about to reclaim the time; give it back cleanly.
            Task { @MainActor in self?.endBackgroundWork(id: id) }
        }
        backgroundTasks[id] = task
    }

    @MainActor
    private func endBackgroundWork(id: String) {
        guard let task = backgroundTasks.removeValue(forKey: id), task != .invalid else { return }
        UIApplication.shared.endBackgroundTask(task)
    }

    override init() {
        super.init()
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {}

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        guard
            let id = message["id"] as? String,
            let text = message["message"] as? String,
            !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
            let messageHandler
        else {
            replyHandler(["accepted": false])
            return
        }

        replyHandler(["accepted": true])
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.beginBackgroundWork(id: id)
            self.sentencesByRequest[id] = []
            let response = await messageHandler(text, id)
            self.deliver(response: response, id: id, using: session)
            self.endBackgroundWork(id: id)
        }
    }

    @MainActor
    func deliverSentence(_ sentence: String, id: String) {
        guard var sentences = sentencesByRequest[id], sentences.count < 1000 else { return }
        let sequence = sentences.count
        sentences.append(sentence)
        sentencesByRequest[id] = sentences
        let session = WCSession.default
        guard session.isReachable else { return }
        session.sendMessage(["id": id, "sentence": sentence, "sequence": sequence], replyHandler: nil, errorHandler: nil)
    }

    @MainActor
    private func deliver(response: String, id: String, using session: WCSession) {
        let sentences = sentencesByRequest.removeValue(forKey: id) ?? []
        let payload: [String: Any] = ["id": id, "response": response, "sentences": sentences]
        if session.isReachable {
            session.sendMessage(payload, replyHandler: nil, errorHandler: nil)
            return
        }
        // Not reachable means the phone answered from the background, or the
        // watch went to sleep waiting. sendMessage would be dropped, so use the
        // queued transfer that survives both sides being suspended. The context
        // is a second chance for a watch that missed the transfer entirely.
        session.transferUserInfo(payload)
        try? session.updateApplicationContext(payload)
    }
}
#endif
