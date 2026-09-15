#if os(iOS)
import AppIntents
import Foundation

/// „Hey Siri, hey JARVIS“: opens the app and starts listening.
///
/// iOS gives no third-party app a wake word once it is closed — only Siri can
/// listen for one. Rather than keep the microphone open in the background all
/// day (battery, and the orange dot), the user chose to let Siri do the waking
/// and hand straight over to JARVIS's own microphone.
struct ListenIntent: AppIntent {
    static let title: LocalizedStringResource = "Mit JARVIS sprechen"
    static let description = IntentDescription("Öffnet JARVIS und hört sofort zu.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        ListenRequest.post()
        return .result()
    }
}

struct JarvisShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ListenIntent(),
            phrases: [
                "Hey \(.applicationName)",
                "Talk to \(.applicationName)",
                "\(.applicationName) listen",
            ],
            shortTitle: "Zuhören",
            systemImageName: "waveform"
        )
    }
}

/// The hand-over from the intent to the view that owns the microphone.
///
/// On a cold start the intent runs before any view exists to hear a
/// notification, so the request is also left standing until the view picks
/// it up.
enum ListenRequest {
    static let notification = Notification.Name("JARVISListenRequested")
    @MainActor private(set) static var pending = false

    @MainActor static func post() {
        pending = true
        NotificationCenter.default.post(name: notification, object: nil)
    }

    /// True once per request.
    @MainActor static func take() -> Bool {
        defer { pending = false }
        return pending
    }
}
#endif
