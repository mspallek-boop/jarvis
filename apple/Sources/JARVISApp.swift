#if os(macOS)
import AppKit
#endif
import SwiftUI

@main
struct JARVISApp: App {
    /// Held, deliberately not observed.
    ///
    /// As a `@StateObject` every published change re-evaluated this whole
    /// Scene, and a Scene carries the main menu: SwiftUI answered each change
    /// by rebuilding the menu bar. `updateRun` mutates `localRuns` once per
    /// streamed token, so an answer arriving meant dozens of menu rebuilds a
    /// second — and one of them landed inside another and threw out of
    /// `-[NSMenu itemArray]`, which is the abort in the crash report.
    ///
    /// Nothing in this Scene needs to react to the model; the views below do,
    /// and they subscribe through `@EnvironmentObject` on their own. `@State`
    /// keeps the object alive for the process without subscribing to it.
    @State private var model = AppModel()
    #if os(macOS)
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    #endif

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
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
