import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var isTyping = false
    @FocusState private var typingFocused: Bool
    @State private var showingFiles = false
    @State private var showingHistory = false
    @State private var voiceControlIsVisible = true
    @Namespace private var thinkingOrbNamespace

    private let chatScrollSpace = "jarvis-chat-scroll"
    private let chatBottomAnchor = "jarvis-chat-bottom"

    private var background: Color {
        model.backgroundChoice.color
    }

    private var ink: Color {
        model.backgroundChoice.foregroundColor
    }

    var body: some View {
        ZStack {
            background.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                connectionBanner
                if isTyping {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            voiceControl
                            ForEach(model.messages) {
                                MessageBubble(message: $0).id($0.id)
                            }
                            if model.isWorking {
                                if !model.liveResponse.isEmpty {
                                    Text(AnswerText.formatted(model.liveResponse))
                                        .font(model.appFont(.body))
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .textSelection(.enabled)
                                        .padding(.vertical, 12)
                                }
                                HStack(spacing: 9) {
                                    ProgressView().tint(ink)
                                    Text(model.activityLabel)
                                        .font(.caption2.monospaced())
                                        .tracking(1.6)
                                    Spacer()
                                }
                                .foregroundStyle(ink.opacity(0.58))
                                .padding(.vertical, 18)
                            }
                            // A fixed target at the very end: the growing answer
                            // has no stable id to scroll to while it streams.
                            Color.clear
                                .frame(height: 1)
                                .id(chatBottomAnchor)
                        }
                        .padding(.horizontal, 20)
                    }
                    .coordinateSpace(name: chatScrollSpace)
                    .scrollIndicators(.hidden)
                    .onPreferenceChange(VoiceControlFramePreferenceKey.self) { frame in
                        let isVisible = !frame.isNull && frame.maxY > 12
                        guard isVisible != voiceControlIsVisible else { return }
                        withAnimation(.snappy(duration: 0.32)) {
                            voiceControlIsVisible = isVisible
                        }
                    }
                    .onChange(of: model.messages.count) {
                        if let last = model.messages.last {
                            withAnimation(.easeOut(duration: 0.18)) {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                    // Follow a long answer as it arrives instead of leaving the
                    // user staring at the top of it. No animation here: this
                    // fires while text is still growing.
                    .onChange(of: model.liveResponse) {
                        proxy.scrollTo(chatBottomAnchor, anchor: .bottom)
                    }
                    .onChange(of: model.activityLabel) {
                        proxy.scrollTo(chatBottomAnchor, anchor: .bottom)
                    }
                }
                } else {
                    voiceStage
                }
                inputHandle
                if isTyping { composer }
            }
        }
        .foregroundStyle(ink)
        .sheet(isPresented: $model.showingSettings) {
            SettingsView().environmentObject(model)
        }
        .sheet(isPresented: $showingFiles) {
            FilesView().environmentObject(model)
        }
        .sheet(isPresented: $showingHistory) {
            ChatHistoryView().environmentObject(model)
        }
        .task {
            await model.setVoiceForeground(true)
            await model.checkConnection()
        }
        .onChange(of: scenePhase) {
            if scenePhase == .background {
                Task { await model.setVoiceForeground(false) }
            } else if scenePhase == .active {
                Task { await model.setVoiceForeground(!isPresentingSheet) }
            }
        }
        .onChange(of: isPresentingSheet) {
            Task { await model.setVoiceForeground(!isPresentingSheet) }
        }
        .onDisappear { Task { await model.setVoiceForeground(false) } }
    }

    private var isPresentingSheet: Bool {
        showingFiles || showingHistory || model.showingSettings
    }

    private var voiceLabel: String {
        if model.speech.isSpeaking { return "Tippen zum Unterbrechen" }
        if model.isWorking { return model.activityLabel }
        if model.speech.isListening { return "Ich höre zu" }
        return "Tippen zum Sprechen"
    }

    private var voiceStage: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 20)
            largeOrbButton
            Text(voiceLabel)
                .font(model.appFont(.caption))
                .tracking(1.4)
                .foregroundStyle(ink.opacity(0.45))
            if let error = model.speech.errorMessage ?? model.lastError {
                Text(error)
                    .font(model.appFont(.callout))
                    .foregroundStyle(ink.opacity(0.65))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 28)
            } else if !model.speech.transcript.isEmpty && model.speech.isListening {
                Text(model.speech.transcript)
                    .font(model.appFont(.title3))
                    .multilineTextAlignment(.center)
                    .lineLimit(5)
                    .padding(.horizontal, 28)
            } else if model.isWorking && !model.liveResponse.isEmpty {
                ScrollView {
                    Text(AnswerText.formatted(model.liveResponse))
                        .font(model.appFont(.callout))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                }
                .frame(maxHeight: 150)
                .padding(.horizontal, 28)
            } else if let last = model.messages.last, model.messages.count > 1 {
                ScrollView {
                    Text(last.role == .jarvis ? AnswerText.formatted(last.text) : AttributedString(last.text))
                        .font(model.appFont(.callout))
                        .foregroundStyle(ink.opacity(0.65))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                }
                .scrollIndicators(.hidden)
                .frame(maxHeight: 150)
                .padding(.horizontal, 28)
            }
            Spacer(minLength: 20)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var inputHandle: some View {
        Button {
            withAnimation(.easeInOut(duration: 0.25)) { isTyping.toggle() }
            typingFocused = isTyping
            Task { await model.setTyping(isTyping) }
        } label: {
            Capsule()
                .fill(ink.opacity(0.20))
                .frame(width: 48, height: 3)
                .frame(maxWidth: .infinity)
                .frame(height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isTyping ? "Zurück zum Sprachmodus" : "Texteingabe öffnen")
        .help(isTyping ? "Sprachmodus" : "Tippen")
    }

    private var header: some View {
        HStack(spacing: 14) {
            Text("JARVIS")
                .font(model.appFont(.caption, weight: .semibold))
                .tracking(2.4)
            Circle()
                .fill(ink.opacity(model.connection == .online ? 1 : connectionOpacity))
                .frame(width: 5, height: 5)
                .accessibilityLabel(model.connection.label)
            Spacer()
            if model.connection == .sleeping {
                Button {
                    Task { await model.wakeMac() }
                } label: {
                    Image(systemName: "power")
                        .frame(width: 34, height: 34)
                        .background(Circle().fill(ink.opacity(0.08)))
                }
                .accessibilityLabel("Mac wecken")
            }
            Button { showingHistory = true } label: {
                Image(systemName: "clock.arrow.circlepath")
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(ink.opacity(0.08)))
            }
            .accessibilityLabel("Chatverlauf")
            Button { showingFiles = true } label: {
                Image(systemName: "folder")
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(ink.opacity(0.08)))
            }
            .accessibilityLabel("Mac-Dateien")
            Button { model.showingSettings = true } label: {
                Image(systemName: "slider.horizontal.3")
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(ink.opacity(0.08)))
            }
            .accessibilityLabel("Einstellungen")
        }
        .font(.body)
        .foregroundStyle(ink)
        .buttonStyle(.plain)
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(background)
    }

    @ViewBuilder
    private var connectionBanner: some View {
        switch model.connection {
        case .checking:
            statusBanner(icon: "arrow.triangle.2.circlepath", text: "Verbindung wird geprüft …")
        case .sleeping:
            statusBanner(icon: "moon.zzz", text: "Der Mac schläft.", actionIcon: "power") {
                Task { await model.wakeMac() }
            }
        case .offline(let reason):
            statusBanner(icon: "wifi.slash", text: reason, actionIcon: "arrow.clockwise") {
                Task { await model.checkConnection() }
            }
        default:
            EmptyView()
        }
    }

    private func statusBanner(
        icon: String,
        text: String,
        actionIcon: String? = nil,
        action: (() -> Void)? = nil
    ) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
            Text(text)
                .font(model.appFont(.caption))
                .lineLimit(2)
            Spacer(minLength: 8)
            if let actionIcon, let action {
                Button(action: action) {
                    Image(systemName: actionIcon)
                        .frame(width: 30, height: 30)
                        .background(Circle().fill(ink.opacity(0.10)))
                }
                .buttonStyle(.plain)
            }
        }
        .foregroundStyle(ink.opacity(0.72))
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(ink.opacity(0.055))
    }

    private var voiceControl: some View {
        VStack(spacing: 16) {
            if showCompactThinkingOrb {
                largeOrbButton
                    .hidden()
                    .accessibilityHidden(true)
            } else {
                largeOrbButton
                    .matchedGeometryEffect(id: "thinking-orb", in: thinkingOrbNamespace)
            }

            if model.speech.isListening && !model.speech.transcript.isEmpty {
                Text(model.speech.transcript)
                    .font(model.appFont(.callout))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(ink.opacity(0.82))
                    .padding(.horizontal)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 38)
        .padding(.bottom, 32)
        .background {
            GeometryReader { proxy in
                Color.clear.preference(
                    key: VoiceControlFramePreferenceKey.self,
                    value: proxy.frame(in: .named(chatScrollSpace))
                )
            }
        }
    }

    private var largeOrbButton: some View {
        Button {
            Task { await model.toggleListening() }
        } label: {
            OrbView(
                active: model.connection == .online || model.speech.isSpeaking,
                listening: model.speech.isListening,
                thinking: model.isWorking,
                color: ink
            )
            .contentShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        }
        .buttonStyle(CubeButtonStyle())
        #if os(macOS)
        .focusable(false)
        .focusEffectDisabled()
        #endif
        .accessibilityLabel(model.isWorking ? "Anfrage abbrechen" : model.speech.isSpeaking ? "Antwort unterbrechen" : model.speech.isListening ? "Sprachaufnahme beenden" : "Sprachmodus starten")
    }

    private var showCompactThinkingOrb: Bool {
        model.isWorking && !voiceControlIsVisible
    }

    private var connectionOpacity: Double {
        switch model.connection {
        case .online: return 1
        case .checking: return 0.55
        case .sleeping: return 0.35
        default: return 0.18
        }
    }

    /// The picture waiting to go out with the next message.
    private var pendingImageChip: some View {
        HStack(spacing: 10) {
            if let data = model.pendingImageData, let image = PlatformImage.from(data) {
                image
                    .resizable()
                    .scaledToFill()
                    .frame(width: 44, height: 44)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            Text(model.isUploadingImage ? "Bild wird übertragen …" : "Bild angehängt")
                .font(model.appFont(.caption))
                .foregroundStyle(ink.opacity(0.7))
            Spacer(minLength: 0)
            Button {
                model.discardPendingImage()
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(ink.opacity(0.45))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Bild entfernen")
        }
        .padding(.horizontal, 20)
        .padding(.top, 10)
    }

    private var composer: some View {
        VStack(spacing: 0) {
        if model.pendingImageData != nil || model.isUploadingImage { pendingImageChip }
        HStack(spacing: 10) {
            if showCompactThinkingOrb {
                OrbView(
                    active: true,
                    listening: false,
                    thinking: true,
                    size: 36,
                    color: ink
                )
                .matchedGeometryEffect(id: "thinking-orb", in: thinkingOrbNamespace)
                .frame(width: 40, height: 44)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("JARVIS denkt")
                .transition(.scale(scale: 0.8).combined(with: .opacity))
            }
            TextField("Nachricht", text: $model.input, axis: .vertical)
                .focused($typingFocused)
                .lineLimit(1...4)
                .textFieldStyle(.plain)
                .font(model.appFont(.body))
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .overlay {
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .stroke(ink.opacity(0.20), lineWidth: 1)
                }
                .onSubmit { Task { await model.send() } }
            #if os(iOS)
            if PlatformImage.clipboardHasImage {
                Button {
                    Task { await model.attachClipboardImage() }
                } label: {
                    Image(systemName: "photo.on.rectangle")
                        .font(model.appFont(.body))
                        .foregroundStyle(ink.opacity(0.7))
                        .frame(width: 36, height: 44)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Bild aus der Zwischenablage einfügen")
            }
            #endif
            Button {
                Task { await model.send() }
            } label: {
                Image(systemName: "arrow.up")
                    .font(model.appFont(.headline, weight: .semibold))
                    .foregroundStyle(background)
                    .frame(width: 44, height: 44)
                    .background(Circle().fill(ink))
            }
            .buttonStyle(.plain)
            .disabled(model.cannotSend)
            .opacity(model.cannotSend ? 0.35 : 1)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        }
        .background(background)
        .animation(.snappy(duration: 0.32), value: showCompactThinkingOrb)
        // ⌘V on the Mac takes a picture straight from the clipboard. iOS has no
        // paste command for a view, so the composer offers a button instead.
        #if os(macOS)
        .onPasteCommand(of: PlatformImage.pasteTypes) { providers in
            Task { await model.attachPastedImage(from: providers) }
        }
        #endif
    }
}

private struct VoiceControlFramePreferenceKey: PreferenceKey {
    static let defaultValue: CGRect = .null

    static func reduce(value: inout CGRect, nextValue: () -> CGRect) {
        value = nextValue()
    }
}

private struct ChatHistoryView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var conversationToDelete: ChatConversation?

    var body: some View {
        NavigationStack {
            List(model.conversations) { conversation in
                Button {
                    model.selectConversation(conversation.id)
                    dismiss()
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: conversation.id == model.conversation ? "bubble.left.and.bubble.right.fill" : "bubble.left.and.bubble.right")
                            .foregroundStyle(conversation.id == model.conversation ? Color.accentColor : .secondary)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(conversation.title)
                                .font(model.appFont(.body, weight: .medium))
                                .lineLimit(1)
                            if let preview = conversation.messages.last(where: { $0.role != .system })?.text {
                                Text(preview)
                                    .font(model.appFont(.caption))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                        Spacer()
                        Text(conversation.updatedAt, style: .relative)
                            .font(model.appFont(.caption2))
                            .foregroundStyle(.tertiary)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(model.isWorking)
                .swipeActions {
                    Button(role: .destructive) {
                        conversationToDelete = conversation
                    } label: {
                        Label("Löschen", systemImage: "trash")
                    }
                }
                .contextMenu {
                    Button(role: .destructive) {
                        conversationToDelete = conversation
                    } label: {
                        Label("Chat löschen", systemImage: "trash")
                    }
                }
            }
            .navigationTitle("Chatverlauf")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Schließen") { dismiss() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        model.startNewConversation()
                        dismiss()
                    } label: {
                        Label("Neuer Chat", systemImage: "square.and.pencil")
                    }
                    .disabled(model.isWorking)
                }
            }
            .alert("Chat löschen?", isPresented: Binding(
                get: { conversationToDelete != nil },
                set: { if !$0 { conversationToDelete = nil } }
            )) {
                Button("Abbrechen", role: .cancel) { conversationToDelete = nil }
                Button("Löschen", role: .destructive) {
                    if let conversationToDelete {
                        model.deleteConversation(conversationToDelete.id)
                    }
                    conversationToDelete = nil
                }
            } message: {
                Text("Der lokale Verlauf wird von diesem Gerät entfernt.")
            }
        }
        #if os(macOS)
        .frame(minWidth: 560, minHeight: 520)
        #endif
    }
}

private struct CubeButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.7 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
