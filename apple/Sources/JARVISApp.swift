#if os(macOS)
import AppKit
#endif
import SwiftUI

@main
struct JARVISApp: App {
    @StateObject private var model = AppModel()
    #if os(macOS)
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    #endif

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .preferredColorScheme(model.theme.colorScheme)
                .tint(.blue)
                #if os(macOS)
                // The delegate is built by SwiftUI, so it cannot hold the model
                // from its initialiser. Weakly, and here, is the one place the
                // two are both available.
                .onAppear { appDelegate.model = model }
                #endif
        }
        #if os(macOS)
        .defaultSize(width: 920, height: 720)
        .windowStyle(.hiddenTitleBar)
        .commands {
            // Replaces the standard Hide so ⌘H folds the window into the pill
            // instead of making it disappear. The system hide still works as a
            // fallback — ContentView listens for it too.
            CommandGroup(replacing: .appVisibility) {
                Button("Ausblenden") { model.collapseToOverlay() }
                    .keyboardShortcut("h", modifiers: .command)
                Button("Andere ausblenden") { NSApp.hideOtherApplications(nil) }
                    .keyboardShortcut("h", modifiers: [.command, .option])
            }
        }
        #endif

    }
}
