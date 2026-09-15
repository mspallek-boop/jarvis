"""Guards for the butler voice pipeline and the coloured lock screen.

The Apple project has no XCTest target, so these are static checks on the
source, in the same style as the other Apple guards in this suite.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLE = ROOT / "apple"
PLAYER = (APPLE / "Sources" / "Services" / "NeuralSpeechPlayer.swift").read_text(encoding="utf-8")
CONTROLLER = (APPLE / "Sources" / "Services" / "SpeechController.swift").read_text(encoding="utf-8")
MODEL = (APPLE / "Sources" / "Stores" / "AppModel.swift").read_text(encoding="utf-8")
SHARED = (APPLE / "Shared" / "JarvisActivityAttributes.swift").read_text(encoding="utf-8")
WIDGET = (APPLE / "LiveActivity" / "JarvisLiveActivity.swift").read_text(encoding="utf-8")
BRIDGE = (ROOT / "bridge" / "jarvis_bridge.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------ no gaps

def test_sentences_are_fetched_ahead_of_playback():
    """The old shape asked for the next sentence only after the previous one
    had finished playing, so every boundary cost a full round trip — measured
    at six tenths of a second to well over one against OpenAI."""
    assert "func beginQueue(" in PLAYER
    assert "func enqueue(" in PLAYER
    assert "func endQueue(" in PLAYER
    assert "private func startFeeder()" in PLAYER


def test_the_engine_is_not_torn_down_between_sentences():
    # `stop()` ends the engine; it must not be reachable from the per-sentence
    # path, only from a real stop and from the end of the whole answer.
    feeder = PLAYER[PLAYER.index("private func fetchAndSchedule"):]
    body = feeder[:feeder.index("private func startEngineIfNeeded")]
    assert "stop()" not in body
    assert "startEngineIfNeeded()" in body


def test_streamed_sentences_go_into_the_queue_not_one_at_a_time():
    enqueue = CONTROLLER[CONTROLLER.index("func enqueueSentence"):]
    enqueue = enqueue[:enqueue.index("func endStream")]
    # The queue call may carry a Messmodus sequence number; what matters is that
    # the sentence goes into the queue instead of being played one at a time.
    assert "neuralPlayer.enqueue(text" in enqueue
    assert "openNeuralStream(client: client)" in enqueue


# --------------------------------------------------------- the chosen voice

def test_the_chosen_voice_survives_quitting_the_app():
    """It was not forgotten by accident: `init` deleted it on every launch."""
    assert 'UserDefaults.standard.string(forKey: "selectedBridgeVoice") ?? ""' in MODEL
    assert 'private static let voiceMigrationKey = "didDropLegacyProviderVoice"' in MODEL
    init_block = MODEL[MODEL.index("    init() {"):]
    drop = init_block.index('removeObject(forKey: "selectedBridgeVoice")')
    guard = init_block.index("if !UserDefaults.standard.bool(forKey: Self.voiceMigrationKey)")
    assert guard < drop, "the one-time cleanup must be guarded by its flag"


def test_an_unreachable_mac_does_not_clear_the_chosen_voice():
    load = MODEL[MODEL.index("func loadVoices()"):]
    load = load[:load.index("private var chatTasks")]
    assert "!availableBridgeVoices.isEmpty," in load


# -------------------------------------------------------------- the butler

def test_the_voice_list_carries_the_newer_voices():
    voices = BRIDGE[BRIDGE.index("OPENAI_VOICES = "):]
    voices = voices[:voices.index("DEFAULT_OPENAI_INSTRUCTIONS")]
    for name in ("cedar", "marin", "ash", "onyx", "ballad"):
        assert f'"{name}"' in voices


def test_the_instruction_asks_for_pace_and_against_pauses():
    instruction = BRIDGE[BRIDGE.index("DEFAULT_OPENAI_INSTRUCTIONS = "):]
    instruction = instruction[:instruction.index("def openai_voices")]
    assert "Butler" in instruction
    # Both halves of the complaint: too slow, and gaps between sentences.
    assert "zügig" in instruction
    assert "Pausen" in instruction


# --------------------------------------------------- the coloured lock screen

def test_the_lock_screen_wears_the_app_colour_and_the_island_stays_black():
    assert "var background: String" in SHARED
    assert "enum ActivityPalette" in SHARED
    assert ".activityBackgroundTint(ground)" in WIDGET
    # The Dynamic Island is a hole in the display; tinting it looks like a bug.
    island = WIDGET[WIDGET.index("} dynamicIsland: { context in"):]
    assert "activityBackgroundTint" not in island
    assert "background: backgroundChoice.rawValue" in MODEL


def test_the_palette_matches_the_app_and_stays_legible():
    """The extension cannot link the app's model, so the palette is mirrored.
    A colour that drifts between the two would show as a mismatched card."""
    app = MODEL[MODEL.index("enum AppBackground"):]
    app = app[:app.index("enum AppFontFamily")]
    names = [n for n in ("black", "white", "blue", "green", "orange", "red", "purple")
             if f"case {n}\n" in app]
    assert len(names) == 7
    for name in names:
        assert f'case "{name}"' in SHARED or name == "black", f"{name} missing from the mirror"
    # Dark ink on the light grounds, light ink on the dark ones.
    foreground = SHARED[SHARED.index("static func foreground"):]
    assert '"white", "green", "orange"' in foreground


# ------------------------------------------------------------ barge-in (B/4)

DETECTOR = (APPLE / "Sources" / "Services" / "BargeInDetector.swift").read_text(encoding="utf-8")


def test_stopp_and_warte_always_interrupt():
    """Decided 2026-09-15: a signal word beats the echo filter."""
    assert '["stopp", "stop", "warte"]' in DETECTOR
    judge = DETECTOR[DETECTOR.index("mutating func shouldInterrupt"):]
    # The signal check must come before the echo check, or a "Stopp" inside the
    # sentence being read would still be swallowed.
    assert judge.index("signalWords") < judge.index("spokenWords.contains")


def test_the_echo_filter_follows_what_is_heard_not_what_is_queued():
    enqueue = CONTROLLER[CONTROLLER.index("func enqueueSentence"):]
    enqueue = enqueue[:enqueue.index("func endStream")]
    assert "bargeIn.nowSpeaking(text)" not in enqueue
    assert "onSentenceAudible" in PLAYER and "completionCallbackType: .dataPlayedBack" in PLAYER
    wiring = CONTROLLER[CONTROLLER.index("neuralPlayer.onSentenceAudible"):]
    assert "bargeIn.nowSpeaking(text)" in wiring[:wiring.index("neuralPlayer.onSentencePlayed")]


# ------------------------------------------------------ buffered answer (B/2)

def test_the_wait_is_bridged_with_a_fixed_word_not_model_text():
    """Decided 2026-09-15: no early streaming; a local "Moment." instead."""
    send = MODEL[MODEL.index("    func send(_ explicitText: String? = nil) async {"):]
    send = send[:send.index("/// Stops one Hermes turn")]
    assert 'enqueueSentence("Moment.", measured: false)' in send
    assert "filler?.cancel()" in send
    # Fixed words stay out of the Messmodus first-sentence numbers.
    assert "if timingRunID != nil && measured" in CONTROLLER


# ------------------------------------------------------- Siri wakes the phone

INTENT = (APPLE / "Sources" / "Services" / "ListenIntent.swift").read_text(encoding="utf-8")
PROJECT = (APPLE / "JARVIS.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
CONTENT = (APPLE / "Sources" / "Views" / "ContentView.swift").read_text(encoding="utf-8")


def test_siri_opens_jarvis_listening_instead_of_a_background_microphone():
    """Decided 2026-09-15: no always-on iPhone wake word, a Siri shortcut."""
    assert "static let openAppWhenRun = true" in INTENT
    assert "AppShortcutsProvider" in INTENT
    # Both a running app and a cold start by Siri must start listening.
    assert "publisher(for: ListenRequest.notification)" in CONTENT
    assert "if ListenRequest.take() { await model.speech.start() }" in CONTENT
    # The iOS background modes stay audio-only: no microphone kept alive.
    plist = (APPLE / "Config" / "JARVIS-iOS-Info.plist").read_text(encoding="utf-8")
    modes = plist[plist.index("<key>UIBackgroundModes</key>"):]
    assert modes[:modes.index("</array>")].count("<string>") == 1


def test_the_siri_files_are_really_built():
    """The project lists files by hand; an unlisted file is silently skipped."""
    assert "ListenIntent.swift in Sources" in PROJECT
    assert "AppShortcuts.xcstrings in Resources" in PROJECT
    # A German Siri only matches phrases that have a German localisation.
    strings = (APPLE / "Sources" / "Services" / "AppShortcuts.xcstrings").read_text(encoding="utf-8")
    assert '"de"' in strings and "${applicationName}" in strings
    assert "\t\t\t\tde,\n" in PROJECT
