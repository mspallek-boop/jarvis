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
    }
}
