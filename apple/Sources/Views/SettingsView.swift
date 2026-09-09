import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    private var fontScaleLabel: String {
        "\(Int((model.fontScale * 100).rounded())) %"
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Verbindung") {
                    TextField(
                        "Server-Adresse",
                        text: $model.serverURL,
                        prompt: Text(AppModel.defaultServerURL)
                    )
                        .textContentType(.URL)
                    SecureField("JARVIS App-Token", text: $model.token)
                    Button("Verbindung testen") {
                        model.saveSettings()
                        Task { await model.checkConnection() }
                    }
                    LabeledContent("Status", value: model.connection.label)
                }
                Section("Sprache") {
                    Toggle("Antworten vorlesen", isOn: $model.speaksReplies)
                    Toggle("Natürliche Stimme vom Mac", isOn: Binding(
                        get: { model.speech.usesNaturalVoice },
                        set: { model.speech.usesNaturalVoice = $0 }
                    ))
                    Text("Die Stimme kommt vom Sprachanbieter deines Macs. Fällt er aus, übernimmt die Systemstimme, damit die Antwort hörbar bleibt.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    // Grouped, and the cloud group says plainly that it is a
                    // dead end: the monthly ElevenLabs allowance on this
                    // account empties in days, which is what made JARVIS mute.
                    Picker("Stimme", selection: $model.selectedBridgeVoice) {
                        Text("Wie am Mac eingestellt").tag("")
                        ForEach(model.voiceGroups) { group in
                            Section(group.deprecated ? "\(group.title) — veraltet" : group.title) {
                                ForEach(group.voices) { voice in
                                    Text(voice.label).tag(voice.id)
                                }
                            }
                        }
                    }
                    .pickerStyle(.menu)
                    ForEach(model.voiceGroups) { group in
                        if !group.note.isEmpty {
                            Text("\(group.title): \(group.note)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        if let problem = group.error, !problem.isEmpty {
                            Text(problem)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    if let problem = model.voiceListError {
                        Text(problem)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Button("Stimmen neu laden") {
                        Task { await model.loadVoices() }
                    }
                    Picker("Sprechtempo", selection: Binding(
                        get: { model.speech.playbackSpeed },
                        set: { model.speech.playbackSpeed = $0 }
                    )) {
                        ForEach(SpeechPlaybackSpeed.allCases) { speed in
                            Text(speed.label).tag(speed)
                        }
                    }
                    .pickerStyle(.menu)
                    Text("Gilt auf diesem Gerät. Die natürliche Stimme ändert ihr Tempo sofort, die Systemstimme ab dem nächsten Satz. 1× ist das normale Tempo.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Stimme testen") {
                        let client = try? model.makeClient()
                        model.speech.speak("Guten Abend, sir. JARVIS ist bereit. Womit darf ich helfen?", neuralClient: client)
                    }
                    #if os(macOS)
                    Divider()
                    Toggle("Tastenkürzel zum Sprechen", isOn: Binding(
                        get: { model.hotkey.enabled },
                        set: { model.hotkey.enabled = $0 }
                    ))
                    Picker("Taste", selection: Binding(
                        get: { model.hotkey.key },
                        set: { model.hotkey.key = $0 }
                    )) {
                        ForEach(HotkeyMonitor.Key.allCases) { key in
                            Text(key.label).tag(key)
                        }
                    }
                    .pickerStyle(.menu)
                    .disabled(!model.hotkey.enabled)
                    Text("Halten und sprechen, loslassen sendet. Zweimal kurz tippen lässt das Mikrofon offen, bis du wieder doppelt tippst. Modifier-Tasten tippen nichts, sind also auch in einem Textfeld gefahrlos zu halten.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Divider()
                    Toggle("„Hey JARVIS“ hört immer mit", isOn: $model.wakeWordEnabled)
                        .disabled(!model.wakeWordAvailable)
                    Text(model.wakeWordAvailable
                         ? "Aus bedeutet, dass der Weckwort-Dienst das Mikrofon ganz loslässt: kein orangener Punkt und nichts, was den Ton des Macs leiser macht. JARVIS bleibt über das Tastenkürzel und das Fenster erreichbar."
                         : "Der Weckwort-Dienst ist auf diesem Mac nicht eingerichtet.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if model.hotkey.enabled && !model.hotkey.permissionGranted {
                        // A global monitor silently receives nothing without
                        // this, so the feature would look broken rather than
                        // unpermitted.
                        Text("macOS lässt Tasten anderer Apps nur mit Bedienungshilfen-Freigabe mitlesen. Ohne sie wirkt das Kürzel nur, während JARVIS vorne ist.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Button("Bedienungshilfen freigeben…") { model.hotkey.requestPermission() }
                    }
                    Divider()
                    #endif
                    Toggle("Durch Sprechen unterbrechen", isOn: Binding(
                        get: { model.speech.interruptsBySpeaking },
                        set: { model.speech.interruptsBySpeaking = $0 }
                    ))
                    Text("JARVIS hört während des Vorlesens weiter zu und hält an, sobald du zu sprechen beginnst. In lauter Umgebung besser aus.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Picker("Redepause bis zum Senden", selection: Binding(
                        get: { model.speech.utterancePause },
                        set: { model.speech.utterancePause = $0 }
                    )) {
                        Text("0,8 Sekunden").tag(0.8)
                        Text("1,6 Sekunden").tag(1.6)
                        Text("2,5 Sekunden").tag(2.5)
                        Text("4 Sekunden").tag(4.0)
                    }
                    .pickerStyle(.menu)
                    Text("So lange darfst du stocken, ohne dass JARVIS den Satz für beendet hält. Kürzer heißt schneller, aber er fällt dir öfter ins Wort.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Picker("Zuhören endet nach", selection: Binding(
                        get: { model.speech.listeningTimeout },
                        set: { model.speech.listeningTimeout = $0 }
                    )) {
                        Text("10 Sekunden").tag(10.0)
                        Text("30 Sekunden").tag(30.0)
                        Text("2 Minuten").tag(120.0)
                        Text("5 Minuten").tag(300.0)
                        Text("Nie").tag(0.0)
                    }
                    .pickerStyle(.menu)
                    Text("Nach dieser Stille schaltet das Mikrofon ab. Während JARVIS denkt oder spricht, läuft es weiter, und die Zeit beginnt erst, wenn er ausgeredet hat. Tippe auf den Orb, um wieder zu starten.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Eigene Wörter")
                        TextField("Skyr, JARVIS, Hermes", text: Binding(
                            get: { model.speech.recognitionVocabulary.joined(separator: ", ") },
                            set: { entered in
                                model.speech.recognitionVocabulary = entered
                                    .components(separatedBy: ",")
                                    .map { $0.trimmingCharacters(in: .whitespaces) }
                                    .filter { !$0.isEmpty }
                            }
                        ))
                        .textFieldStyle(.roundedBorder)
                        Text("Namen, die die Spracherkennung sonst verschreibt — etwa „Skyr“ als „Skar“. Kommagetrennt.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text("Wenn verfügbar, nutzt JARVIS die lokale Apple-Spracherkennung, sonst Apples Spracherkennungsdienst. Audio wird nicht an die Mac-Bridge übertragen.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("Darstellung") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Modus")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Picker("Modus", selection: $model.theme) {
                            ForEach(AppTheme.allCases) { theme in
                                Text(theme.label).tag(theme)
                            }
                        }
                        .labelsHidden()
                        .pickerStyle(.segmented)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("Hintergrundfarbe")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        HStack(spacing: 14) {
                            ForEach(AppBackground.allCases) { background in
                                backgroundButton(background)
                            }
                        }
                    }

                    Picker("Schriftart", selection: $model.fontFamily) {
                        ForEach(AppFontFamily.allCases) { family in
                            Text(family.label)
                                .font(family.previewFont(size: 15))
                                .tag(family)
                        }
                    }
                    .pickerStyle(.menu)

                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Schriftgröße")
                            Spacer()
                            Text(fontScaleLabel)
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        HStack(spacing: 12) {
                            Text("A").font(.caption)
                            Slider(value: $model.fontScale, in: 0.8...1.4, step: 0.05)
                            Text("A").font(.title3)
                        }
                    }

                    VStack(alignment: .leading, spacing: 5) {
                        Text("VORSCHAU")
                            .font(.caption2.weight(.semibold))
                            .tracking(1.2)
                            .foregroundStyle(model.backgroundChoice.foregroundColor.opacity(0.62))
                        Text("JARVIS ist bereit.")
                            .font(model.appFont(.body))
                            .foregroundStyle(model.backgroundChoice.foregroundColor)
                            .lineLimit(2)
                            .minimumScaleFactor(0.75)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
                    .background {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(model.backgroundChoice.color)
                    }
                    .overlay {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(Color.primary.opacity(0.14), lineWidth: 1)
                    }

                    Button("Darstellung zurücksetzen") {
                        withAnimation(.easeInOut(duration: 0.18)) {
                            model.resetAppearanceSettings()
                        }
                    }
                }
                Section("Sicherheit") {
                    Text("Nutze unterwegs Tailscale. Öffne keinen JARVIS- oder Hermes-Port direkt am Router.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .formStyle(.grouped)
            .task { await model.loadVoices() }
            .navigationTitle("JARVIS Einstellungen")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Fertig") {
                        dismiss()
                    }
                }
            }
        }
        #if os(macOS)
        .frame(minWidth: 560, idealWidth: 600, minHeight: 640, idealHeight: 720)
        #endif
        .tint(.blue)
        .onDisappear {
            model.saveSettings()
        }
    }

    private func backgroundButton(_ background: AppBackground) -> some View {
        Button {
            model.backgroundChoice = background
        } label: {
            Circle()
                .fill(background.color)
                .frame(width: 28, height: 28)
                .overlay {
                    if model.backgroundChoice == background {
                        Image(systemName: "checkmark")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(background.foregroundColor)
                    }
                }
                .overlay {
                    Circle()
                        .stroke(Color.primary.opacity(model.backgroundChoice == background ? 0.7 : 0.16), lineWidth: 2)
                        .padding(-3)
                }
        }
        .buttonStyle(.plain)
        .accessibilityLabel(background.label)
        .accessibilityAddTraits(model.backgroundChoice == background ? .isSelected : [])
    }
}
