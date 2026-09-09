import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var isTyping = false
    @FocusState private var typingFocused: Bool
    @State private var showingFiles = false
    @State private var showingHistory = false
    @State private var runsExpanded = false
    @State private var openStandinID: String?
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
                if let banner = model.notificationBanner {
                    Text(banner)
                        .font(model.appFont(.caption))
                        .foregroundStyle(ink.opacity(0.72))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 20)
                        .padding(.vertical, 10)
                        .background(ink.opacity(0.055))
                        .onTapGesture { model.dismissNotificationBanner() }
                }
                if isTyping {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 0) {
                            voiceControl
                            ForEach(model.messages) {
                                MessageBubble(message: $0).id($0.id)
                            }
                            if model.isWorking || !model.runs.isEmpty {
                                if !model.liveResponse.isEmpty {
                                    Text(AnswerText.formatted(model.liveResponse))
                                        .font(model.appFont(.body))
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .textSelection(.enabled)
                                        .padding(.vertical, 12)
                                }
                                activityStatus
                                if runsExpanded && model.runs.count > 1 {
                                    ForEach(model.runs) { run in
                                        HStack(spacing: 8) {
                                            Text("──")
                                            Text(run.phaseLabel)
                                            Spacer()
                                            Text(run.elapsedLabel)
                                                .monospacedDigit()
                                        }
                                        .font(model.appFont(.caption2))
                                        .foregroundStyle(ink.opacity(0.48))
                                    }
                                }
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
        // Moved down from the Scene: up there it made the whole App body —
        // and with it the main menu — depend on the model.
        .preferredColorScheme(model.theme.colorScheme)
        #if os(macOS)
        .background {
            ClipboardImagePasteHandler(enabled: !isPresentingSheet) { data in
                withAnimation(.easeInOut(duration: 0.25)) { isTyping = true }
                typingFocused = true
                Task {
                    await model.setTyping(true)
                    await model.attachImage(data)
                }
            }
        }
        #endif
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
            #if os(macOS)
            // A window built fresh — first launch, or the Dock reopening one
            // the user had closed — hands the microphone back to the app.
            // Push-to-talk belongs to the small mode, and a global key grab
            // would fight the app's own handling while the window is in front.
            model.updateHotkeyArming(mainWindowVisible: true)
            #endif
        }
        .onChange(of: scenePhase) {
            if scenePhase == .background {
                Task { await model.setVoiceForeground(false) }
            } else if scenePhase == .active {
                Task {
                    await model.setVoiceForeground(!isPresentingSheet)
                    // Coming back from a dark screen is a return, not a launch,
                    // so the view's `task` does not run again. Without this the
                    // offline banner the suspension produced stayed up forever.
                    await model.resumeFromBackground()
                }
            }
        }
        .onChange(of: isPresentingSheet) {
            Task { await model.setVoiceForeground(!isPresentingSheet) }
        }
        .onDisappear { Task { await model.setVoiceForeground(false) } }
        #if os(macOS)
        // Hiding the app (⌘H) is the moment the overlay earns its place: JARVIS
        // is out of the way but still listening, which is the whole point of a
        // push-to-talk pill. Bringing the app back takes it away again, so the
        // two are never on screen at once.
        // ⌘H is replaced by the collapse (see JARVISApp commands); these cover
        // the paths that still hide or minimise the window some other way.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didHideNotification)) { _ in
            model.collapseToOverlay()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didMiniaturizeNotification)) { note in
            guard !(note.object is NSPanel) else { return }
            model.collapseToOverlay()
        }
        // Closing the window is allowed to mean closed — no pill, nothing on
        // screen. What it must not mean is unreachable: the key stays armed, so
        // holding it wakes JARVIS and the pill comes up out of the Dock.
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.willCloseNotification)) { note in
            guard !(note.object is NSPanel) else { return }
            model.updateHotkeyArming(mainWindowVisible: false)
        }
        #endif
    }

    private var isPresentingSheet: Bool {
        showingFiles || showingHistory || model.showingSettings
    }

    private var voiceLabel: String {
        // The mute has to be visible where the user is looking, or a dead
        // microphone reads as a broken app.
        if model.speech.microphoneMuted { return "Mikrofon stumm" }
        if model.speech.isSpeaking { return "Tippen zum Unterbrechen" }
        if model.isWorking || !model.runs.isEmpty { return activitySummary }
        if model.speech.isListening { return "Ich höre zu" }
        return "Tippen zum Sprechen"
    }

    private var activitySummary: String {
        // `runs` is a polling snapshot from the bridge. It can be empty or
        // stale for up to one poll while this view already owns several live
        // requests, so it must not decide whether multitasking is visible.
        let count = model.localRuns.count
        guard count > 1 else { return model.activityLabel }
        return "Ich " + model.activityLabel + " · +" + String(count - 1)
    }

    @ViewBuilder
    private var activityStatus: some View {
        Group {
            if model.runs.count > 1 {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) { runsExpanded.toggle() }
                } label: {
                    HStack(spacing: 9) {
                        ProgressView().tint(ink)
                        Text(activitySummary)
                            .font(.caption2.monospaced())
                            .tracking(1.2)
                        Spacer()
                        Image(systemName: runsExpanded ? "chevron.up" : "chevron.down")
                            .font(.caption2)
                    }
                }
                .buttonStyle(.plain)
            } else {
                HStack(spacing: 9) {
                    ProgressView().tint(ink)
                    Text(model.activityLabel)
                        .font(.caption2.monospaced())
                        .tracking(1.6)
                    Spacer()
                }
            }
        }
        .foregroundStyle(ink.opacity(0.58))
        .padding(.vertical, 18)
    }

    /// The other running tasks. The focused task is already the large orb, so
    /// it is deliberately not repeated in this row. With the bridge's four
    /// parallel lanes that leaves at most three visible blobs.
    ///
    /// A client can still have more *queued* requests than those lanes. Keep
    /// the row horizontally scrollable for that case: an `HStack` with an
    /// unbounded number of fixed-size buttons eventually overflows its parent
    /// and SwiftUI may drop the entire row during its animated relayout.
    /// One blob per other running task. The focused one is the large orb, so
    /// it is deliberately not repeated here.
    private var blobRow: some View {
        HStack(spacing: 14) {
            ForEach(model.localRuns.filter { $0.id != model.focusedRunID }) { run in
                Button { withAnimation(.easeInOut(duration: 0.28)) { model.focusRun(run.id) } } label: {
                    // Brighter and a little larger than it was: at 30 points and
                    // half opacity a single Bauhaus tile read as a plain grey
                    // square rather than as one of JARVIS's own glyphs.
                    TaskBlobView(size: 34, color: ink, seed: run.id.hashValue)
                        .opacity(0.75)
                        // Small on purpose, but never small to hit.
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                #if os(macOS)
                .focusable(false)
                #endif
                .accessibilityLabel("Aufgabe anzeigen: \(run.prompt.prefix(60))")
                .help(String(run.prompt.prefix(80)))
                .transition(.scale.combined(with: .opacity))
            }
        }
        .padding(.horizontal, 12)
    }

    private var taskBlobs: some View {
        // Centred when the row fits, scrolling when it does not — and neither
        // job may be given to a GeometryReader. That reader is greedy: it
        // claims the space around it and anchors its content top-leading, so
        // the row jumped out of the column and sat in the window's corner.
        // `ViewThatFits` asks the same question without taking any space.
        ViewThatFits(in: .horizontal) {
            blobRow
            ScrollView(.horizontal, showsIndicators: false) { blobRow }
        }
        .frame(maxWidth: .infinity)
        .frame(height: model.localRuns.count > 1 ? 44 : 0)
        .opacity(model.localRuns.count > 1 ? 1 : 0)
        .allowsHitTesting(model.localRuns.count > 1)
        .animation(.easeInOut(duration: 0.25), value: model.localRuns.count)
    }

    /// What is still running without the app: one quiet line per stand-in,
    /// with the time left on it.
    ///
    /// It has to be here, on the page the user actually looks at, because a
    /// stand-in outlives the window. Closing the app does not end it, and
    /// something that answers a real person on your behalf must never be
    /// invisible — the whole failure it exists to prevent is finding out
    /// afterwards. Quiet, not hidden: small, dim, and gone by itself when the
    /// clock runs out.
    private var standingTasks: some View {
        VStack(spacing: 6) {
            ForEach(model.standins) { standin in
                let open = openStandinID == standin.id
                VStack(spacing: 10) {
                    Button {
                        withAnimation(.easeInOut(duration: 0.26)) {
                            openStandinID = open ? nil : standin.id
                        }
                    } label: {
                        TimelineView(.periodic(from: .now, by: 1)) { context in
                            let left = standin.endsAt.timeIntervalSince(context.date)
                            HStack(spacing: 8) {
                                Image(systemName: "person.wave.2")
                                    .font(.system(size: 10))
                                Text(standin.name)
                                Text("·")
                                Text(Self.timeLeft(left))
                                    .monospacedDigit()
                                if standin.exchanges > 0 {
                                    Text("· \(standin.exchanges) \(standin.exchanges == 1 ? "Nachricht" : "Nachrichten")")
                                }
                                if !standin.announced {
                                    // She was never told, so the line says so
                                    // rather than letting the user assume.
                                    Text("· ohne Ansage")
                                }
                                Image(systemName: open ? "chevron.up" : "chevron.down")
                                    .font(.system(size: 8))
                                    .opacity(0.7)
                            }
                            .font(.caption2)
                            .tracking(0.8)
                            .foregroundStyle(ink.opacity(open ? 0.75 : left <= 300 ? 0.62 : 0.4))
                            .contentShape(Rectangle())
                        }
                    }
                    .buttonStyle(.plain)
                    #if os(macOS)
                    .focusable(false)
                    #endif
                    .accessibilityLabel("Vertretung für \(standin.name), \(standin.exchanges) Nachrichten")

                    if open { standinDetail(standin) }
                }
            }
        }
        .animation(.easeInOut(duration: 0.3), value: model.standins)
    }

    /// What has happened in this chat so far, in JARVIS's own words.
    ///
    /// Deliberately his account and not the messages: he already reports in
    /// these words, so opening the task shows the whole run instead of only
    /// the last nudge — without moving anyone's messages out of WhatsApp.
    @ViewBuilder
    private func standinDetail(_ standin: JarvisAPIClient.Standin) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            if standin.history.isEmpty {
                Text("Noch nichts passiert.")
                    .font(.caption2)
                    .foregroundStyle(ink.opacity(0.4))
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 7) {
                        ForEach(Array(standin.history.enumerated()), id: \.offset) { _, note in
                            HStack(alignment: .firstTextBaseline, spacing: 9) {
                                Text(note.time, format: .dateTime.hour().minute())
                                    .monospacedDigit()
                                    .foregroundStyle(ink.opacity(0.32))
                                Text(note.gist)
                                    .foregroundStyle(ink.opacity(note.urgent ? 0.85 : 0.6))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .font(.caption2)
                        }
                    }
                }
                .frame(maxHeight: 160)
            }
            Text("seit \(standin.startedAtLabel)")
                .font(.system(size: 9))
                .foregroundStyle(ink.opacity(0.3))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .frame(maxWidth: 420)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(ink.opacity(0.06))
        )
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    /// "1:54 Std", "54 Min", "gleich" — never a jittering seconds counter for
    /// something that runs for hours.
    static func timeLeft(_ seconds: TimeInterval) -> String {
        let left = max(0, Int(seconds.rounded()))
        if left < 60 { return "gleich vorbei" }
        let minutes = left / 60
        if minutes < 60 { return "noch \(minutes) Min" }
        return "noch \(minutes / 60):\(String(format: "%02d", minutes % 60)) Std"
    }

    private var voiceStage: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 20)
            standingTasks
            // Nothing is drawn while fewer than two tasks run, so an idle app
            // looks exactly as it did before multitasking existed.
            taskBlobs
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
        HStack(spacing: 8) {
            Text("JARVIS")
                .font(model.appFont(.caption, weight: .semibold))
                .tracking(2.4)
            Circle()
                .fill(ink.opacity(model.connection == .online ? 1 : connectionOpacity))
                .frame(width: 5, height: 5)
                .accessibilityLabel(model.connection.label)
            Spacer()
            // Mutes the *microphone*, not JARVIS — the point is to talk to
            // someone else without being listened to. Whether JARVIS reads
            // answers aloud is a different thing and lives in the settings.
            Button { model.speech.setMicrophoneMuted(!model.speech.microphoneMuted) } label: {
                Image(systemName: model.speech.microphoneMuted ? "mic.slash.fill" : "mic")
                    .frame(width: 34, height: 34)
                    .background(Circle().fill(ink.opacity(model.speech.microphoneMuted ? 0.20 : 0.08)))
            }
            .accessibilityLabel(model.speech.microphoneMuted ? "Mikrofon einschalten" : "Mikrofon stummschalten")
            .help(model.speech.microphoneMuted ? "Mikrofon einschalten" : "Mikrofon stummschalten")
            Menu {
                Picker("Sprechtempo", selection: Binding(
                    get: { model.speech.playbackSpeed },
                    set: { model.speech.playbackSpeed = $0 }
                )) {
                    ForEach(SpeechPlaybackSpeed.allCases) { speed in
                        Text(speed.label).tag(speed)
                    }
                }
            } label: {
                Text(model.speech.playbackSpeed.rawValue.formatted(.number.precision(.fractionLength(0...2))) + "×")
                    .font(.caption.monospacedDigit())
                    .frame(minWidth: 34, minHeight: 34)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
            .accessibilityLabel("Sprechtempo: \(model.speech.playbackSpeed.label)")
            .help("Sprechtempo ändern")
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
            .disabled(model.isUploadingImage)
            .accessibilityLabel("Bild entfernen")
        }
        .padding(.horizontal, 20)
        .padding(.top, 10)
    }

    private var composer: some View {
        VStack(spacing: 0) {
        if model.pendingImageData != nil || model.isUploadingImage { pendingImageChip }
        if let error = model.lastError {
            Text(error)
                .font(model.appFont(.caption))
                .foregroundStyle(ink.opacity(0.7))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.top, 8)
        }
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
