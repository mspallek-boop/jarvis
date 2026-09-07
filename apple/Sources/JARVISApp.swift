import SwiftUI

@main
struct JARVISApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .preferredColorScheme(model.theme.colorScheme)
                .tint(.blue)
        }
        #if os(macOS)
        .defaultSize(width: 920, height: 720)
        .windowStyle(.hiddenTitleBar)
        #endif

        #if os(macOS)
        // Same JARVIS, small and above everything, for keeping a conversation
        // going while working in another app. One model, so what is said in one
        // window is there in the other.
        Window("JARVIS", id: "jarvis-overlay") {
            OverlayView()
                .environmentObject(model)
                .background(OverlayWindowConfigurator())
        }
        .defaultSize(width: 224, height: 62)
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
        .keyboardShortcut("j", modifiers: [.command, .shift])
        #endif
    }
}
