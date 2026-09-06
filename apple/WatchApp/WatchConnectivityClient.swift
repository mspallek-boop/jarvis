import AVFoundation
import Combine
import Foundation
import WatchConnectivity
import WatchKit

@MainActor
final class WatchConnectivityClient: NSObject, ObservableObject {
    @Published var isWorking = false
    @Published var response = ""
    @Published var error: String?

    private let session: WCSession? = WCSession.isSupported() ? .default : nil
    private var requestID: String?
    private var timeoutTask: Task<Void, Never>?
    private let synthesizer = AVSpeechSynthesizer()
    private var sentenceQueue = WatchSentenceQueue()

    override init() {
        super.init()
        session?.delegate = self
        session?.activate()
    }

    func send(_ text: String) {
        guard let session else {
            fail("Keine Verbindung zum iPhone.")
            return
        }
        guard session.activationState == .activated, session.isReachable else {
            fail("Öffne JARVIS kurz auf dem iPhone.")
            return
        }

        guard !isWorking else { return }
        synthesizer.stopSpeaking(at: .immediate)
        let id = UUID().uuidString
        requestID = id
        response = ""
        sentenceQueue = WatchSentenceQueue()
        error = nil
        isWorking = true
        timeoutTask?.cancel()
        timeoutTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(430)) } catch { return }
            guard let self, self.requestID == id, self.isWorking else { return }
            self.fail("Die Antwort dauert zu lange. Prüfe JARVIS auf dem iPhone.")
        }
        session.sendMessage(
            ["id": id, "message": text],
            replyHandler: { [weak self] reply in
                guard reply["accepted"] as? Bool == true else {
                    Task { @MainActor in self?.fail("Anfrage wurde nicht angenommen.") }
                    return
                }
            },
            errorHandler: { [weak self] error in
                Task { @MainActor in self?.fail(error.localizedDescription) }
            }
        )
    }

    private func receive(_ message: [String: Any]) {
        guard let id = message["id"] as? String, id == requestID else { return }
        if let sentence = message["sentence"] as? String, let sequence = message["sequence"] as? Int {
            for ready in sentenceQueue.receive(sentence, index: sequence) {
                response += (response.isEmpty ? "" : " ") + ready
                speak(ready)
            }
            return
        }
        guard let text = message["response"] as? String else { return }
        if let sentences = message["sentences"] as? [String], !sentences.isEmpty {
            for ready in sentenceQueue.finish(sentences) { speak(ready) }
        } else if sentenceQueue.deliveredCount == 0 {
            speak(text)
        }
        timeoutTask?.cancel()
        requestID = nil
        response = text
        error = nil
        isWorking = false
        WKInterfaceDevice.current().play(.success)
    }

    private func speak(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "de-DE")
        utterance.rate = 0.47
        synthesizer.speak(utterance)
    }

    private func fail(_ message: String) {
        synthesizer.stopSpeaking(at: .immediate)
        timeoutTask?.cancel()
        requestID = nil
        error = message
        isWorking = false
        WKInterfaceDevice.current().play(.failure)
    }
}

extension WatchConnectivityClient: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        guard let error else { return }
        Task { @MainActor in self.fail(error.localizedDescription) }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor in self.receive(message) }
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        // The queued path the phone uses when it answered from the background.
        Task { @MainActor in self.receive(userInfo) }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        Task { @MainActor in self.receive(applicationContext) }
    }
}
