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
        Window("JARVIS Overlay", id: "jarvis-overlay") {
            OverlayView()
                .environmentObject(model)
                .preferredColorScheme(model.theme.colorScheme)
                .background(FloatingWindowConfigurator())
        }
        .defaultSize(width: 200, height: 180)
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
        .keyboardShortcut("j", modifiers: [.command, .shift])
        #endif
    }
}
