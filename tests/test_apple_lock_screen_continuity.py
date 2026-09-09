"""Regression guards for what the phone shows once its screen goes off.

Locking the phone suspends the app and tears down its sockets. The app read
the resulting URLSession error as a real outage, so it stamped an offline
banner and wrote the error into the chat; nothing re-checked afterwards, so
that banner survived the phone waking up. The turn itself kept running on the
Mac the whole time.

There is deliberately no XCTest target in the Apple project, so these are
static checks on the source, in the same style as the multitasking guards.
"""

from pathlib import Path

APPLE = Path(__file__).resolve().parents[1] / "apple"
APP_MODEL = (APPLE / "Sources" / "Stores" / "AppModel.swift").read_text(encoding="utf-8")
CONTENT_VIEW = (APPLE / "Sources" / "Views" / "ContentView.swift").read_text(encoding="utf-8")
CONTROLLER = (APPLE / "Sources" / "Services" / "LiveActivityController.swift").read_text(encoding="utf-8")
ATTRIBUTES = (APPLE / "Shared" / "JarvisActivityAttributes.swift").read_text(encoding="utf-8")
WIDGET = (APPLE / "LiveActivity" / "JarvisLiveActivity.swift").read_text(encoding="utf-8")
PROJECT = (APPLE / "project.yml").read_text(encoding="utf-8")


def test_a_suspended_app_is_not_reported_as_an_outage():
    assert "private func isSuspensionDrop" in APP_MODEL
    assert "guard !voiceForeground else { return false }" in APP_MODEL
    assert ".networkConnectionLost" in APP_MODEL
    # `unchecked` is the honest state: the next foreground check answers it.
    assert "connection = .unchecked" in APP_MODEL


def test_every_failure_path_goes_through_the_suspension_aware_recorder():
    # A bare `connection = .offline(error.localizedDescription)` in a request's
    # catch block is exactly the bug: it cannot tell a locked screen from a
    # dead Mac. Two are allowed to remain — inside `recordFailure`, which does
    # the telling apart, and inside `wakeMac`, which the user pressed.
    offline_stamps = APP_MODEL.count("connection = .offline(error.localizedDescription)")
    assert offline_stamps == 2, "a request's catch block must call recordFailure instead"
    assert "recordFailure(error, announce: false)" in APP_MODEL
    # The streaming turn is the one that fails when the phone locks.
    stream_catch = APP_MODEL[APP_MODEL.index("guard localRuns.contains(where: { $0.id == id }) else { return }\n            let wasFocused = focusedRunID == id\n            finishRun(id, failure:"):]
    assert "recordFailure(error)" in stream_catch[:400]


def test_returning_to_the_foreground_rechecks_the_connection():
    # SwiftUI's `task` does not run again for a scene that never went away, so
    # without this the stale banner stayed up until the app was killed.
    assert "func resumeFromBackground() async" in APP_MODEL
    start = CONTENT_VIEW.index("onChange(of: scenePhase)")
    phase_block = CONTENT_VIEW[start:start + 700]
    assert "scenePhase == .active" in phase_block
    assert "model.resumeFromBackground()" in phase_block


def test_a_running_turn_is_visible_on_the_lock_screen_and_the_island():
    assert "struct JarvisActivityAttributes: ActivityAttributes" in ATTRIBUTES
    assert "var isFinished: Bool" in ATTRIBUTES
    assert "ActivityConfiguration(for: JarvisActivityAttributes.self)" in WIDGET
    for region in ("compactLeading", "compactTrailing", "minimal", "DynamicIslandExpandedRegion"):
        assert region in WIDGET, f"the Dynamic Island needs its {region} presentation"


def test_the_activity_follows_a_run_from_start_to_finish():
    assert "liveActivity.start(runID: id" in APP_MODEL
    assert "liveActivity.update(runID: id" in APP_MODEL
    assert "liveActivity.finish(runID: id" in APP_MODEL


def test_streamed_tokens_cannot_rate_limit_the_activity_into_staleness():
    # Pushing every delta gets the activity throttled and then ignored, which
    # would freeze the phase on screen — the same "it stopped" impression the
    # Live Activity exists to remove.
    assert "minimumInterval" in CONTROLLER
    assert "scheduleFlush" in CONTROLLER
    assert "areActivitiesEnabled" in CONTROLLER


def test_the_extension_ships_with_the_phone_app():
    assert "NSSupportsLiveActivities: true" in PROJECT
    assert "JARVIS-LiveActivity:" in PROJECT
    live_activity = PROJECT[PROJECT.index("  JARVIS-LiveActivity:"):]
    assert "type: app-extension" in live_activity.split("JARVIS-macOS:")[0]
    ios = PROJECT[PROJECT.index("  JARVIS-iOS:"):PROJECT.index("  JARVIS-LiveActivity:")]
    assert "- target: JARVIS-LiveActivity" in ios and "embed: true" in ios
