"""Regression guards for the native HUD's multitasking affordance.

The Apple project deliberately has no separate XCTest target.  These static
checks protect the two view invariants that caused the HUD to lose its visible
multitasking state when the task row grew.
"""

from pathlib import Path


APPLE = Path(__file__).resolve().parents[1] / "apple" / "Sources" / "Views"
CONTENT_VIEW = (APPLE / "ContentView.swift").read_text(encoding="utf-8")
ORB_VIEW = (APPLE / "OrbView.swift").read_text(encoding="utf-8")


def orb_section(marker: str) -> str:
    start = ORB_VIEW.index(marker)
    end = ORB_VIEW.index("\nstruct ", start + len(marker))
    return ORB_VIEW[start:end]


def section_after(marker: str, end_marker: str) -> str:
    start = CONTENT_VIEW.index(marker)
    end = CONTENT_VIEW.index(end_marker, start)
    return CONTENT_VIEW[start:end]


def test_multitasking_summary_uses_the_immediate_local_run_state():
    summary = section_after("private var activitySummary", "@ViewBuilder\n    private var activityStatus")
    assert "let count = model.localRuns.count" in summary
    assert "String(count - 1)" in summary
    assert "model.runs.count" not in summary


def test_multitasking_splits_into_a_grid_per_task():
    # Two or more tasks split the orb into one grid each, not an orb with blobs.
    assert "struct MultitaskGrids" in ORB_VIEW
    assert "if model.isMultitasking" in CONTENT_VIEW
    assert "MultitaskGrids(tiles: model.taskTiles, focusedID: model.focusedRunID" in CONTENT_VIEW


def test_the_split_grids_are_small_three_by_three_rasters():
    # The user asked for small 3x3 rasters in the split, not a five-by-five that
    # is only legible at the single orb's size.
    grids = orb_section("struct MultitaskGrids")
    assert "columns: 3" in grids


def test_the_split_grids_stay_centred_and_cannot_stick_left():
    """A greedy GeometryReader anchors its content top-leading and would throw
    the row into a corner; ViewThatFits centres when the grids fit and scrolls
    when they do not."""
    grids = orb_section("struct MultitaskGrids")
    assert "ViewThatFits(in: .horizontal)" in grids
    assert "ScrollView(.horizontal, showsIndicators: false)" in grids
    code = "\n".join(line for line in grids.splitlines() if "//" not in line)
    assert "GeometryReader" not in code


def test_the_grids_shrink_before_they_scroll():
    """Seen on an iPhone SE: five tasks at 78pt overflowed into the scroll view,
    which starts at the left edge and cut the fifth grid off unseen."""
    grids = orb_section("struct MultitaskGrids")
    fits = grids[grids.index("ViewThatFits(in: .horizontal)"):]
    fits = fits[:fits.index("ScrollView(.horizontal")]
    for rung in ("strip(side: side)", "strip(side: 64)", "strip(side: 52)", "strip(side: 44)"):
        assert rung in fits
    # A conditional rung would be an empty child that "fits" and shows nothing.
    code = "\n".join(line for line in fits.splitlines() if "//" not in line)
    assert "if " not in code
