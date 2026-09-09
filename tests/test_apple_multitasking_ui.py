"""Regression guards for the native HUD's multitasking affordance.

The Apple project deliberately has no separate XCTest target.  These static
checks protect the two view invariants that caused the HUD to lose its visible
multitasking state when the task row grew.
"""

from pathlib import Path


CONTENT_VIEW = (
    Path(__file__).resolve().parents[1] / "apple" / "Sources" / "Views" / "ContentView.swift"
).read_text(encoding="utf-8")


def section_after(marker: str, end_marker: str) -> str:
    start = CONTENT_VIEW.index(marker)
    end = CONTENT_VIEW.index(end_marker, start)
    return CONTENT_VIEW[start:end]


def test_multitasking_summary_uses_the_immediate_local_run_state():
    summary = section_after("private var activitySummary", "@ViewBuilder\n    private var activityStatus")
    assert "let count = model.localRuns.count" in summary
    assert "String(count - 1)" in summary
    assert "model.runs.count" not in summary


def test_task_blob_row_excludes_the_center_orb_and_cannot_overflow():
    row = section_after("private var blobRow", "private var taskBlobs")
    assert "model.localRuns.filter { $0.id != model.focusedRunID }" in row
    blobs = section_after("private var taskBlobs", "/// What is still running")
    # Centred when it fits, scrolling when it does not.
    assert "ViewThatFits(in: .horizontal)" in blobs
    assert "ScrollView(.horizontal, showsIndicators: false) { blobRow }" in blobs


def test_the_blob_row_never_uses_a_geometry_reader():
    """GeometryReader is greedy: it claims the space around it and anchors its
    content top-leading, which threw the row into the window's corner on the
    Mac. A horizontal ScrollView also cannot centre with `maxWidth: .infinity`,
    because inside one that resolves to the row's own width."""
    blobs = section_after("private var blobRow", "/// What is still running")
    code = "\n".join(line for line in blobs.splitlines() if "//" not in line)
    assert "GeometryReader" not in code
    assert "maxWidth: .infinity, alignment: .center" not in code
