import SwiftUI
import WatchKit

struct WatchContentView: View {
    @StateObject private var bridge = WatchConnectivityClient()
    @State private var isDictating = false

    var body: some View {
        VStack(spacing: 12) {
            Button(action: beginDictation) {
                OrbView(
                    active: isDictating || bridge.isWorking,
                    listening: isDictating,
                    thinking: bridge.isWorking,
                    size: 94
                )
            }
            .buttonStyle(.plain)
            .disabled(bridge.isWorking)
            .accessibilityLabel("Mit JARVIS sprechen")

            if bridge.isWorking {
                ProgressView()
                    .controlSize(.mini)
            } else if let error = bridge.error {
                Text(error)
                    .foregroundStyle(.secondary)
                    .font(.caption2)
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
            } else if !bridge.response.isEmpty {
                ScrollView {
                    Text(bridge.response)
                        .font(.caption2)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                }
                .frame(maxHeight: 56)
            }
        }
        .padding(.horizontal, 8)
        .task {
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled else { return }
            beginDictation()
        }
    }

    private func beginDictation() {
        guard
            !bridge.isWorking,
            let controller = WKExtension.shared().visibleInterfaceController
        else { return }

        isDictating = true
        controller.presentTextInputController(withSuggestions: [], allowedInputMode: .plain) { results in
            Task { @MainActor in
                isDictating = false
                guard let text = results?.first as? String else { return }
                bridge.send(text)
            }
        }
    }
}
