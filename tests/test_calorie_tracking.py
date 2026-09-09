"""Offline tests for the durable local calorie diary and its FastAPI surface."""

from __future__ import annotations

from datetime import date

from calorie_tracker import CalorieTracker, CalorieValidationError


def test_tracker_persists_entries_and_computes_daily_remaining(tmp_path):
    path = tmp_path / "calories.sqlite3"
    tracker = CalorieTracker(path)
    tracker.set_goal({"daily_calories": 2200, "effective_from": "2026-09-07"})
    first = tracker.add_entry({
        "calories": 450, "description": "  oatmeal   with berries ", "meal": "breakfast",
        "occurred_at": "2026-09-08T08:15:00+02:00",
    })
    tracker.add_entry({
        "calories": 700, "description": "lentil bowl", "occurred_at": "2026-09-08T13:00:00+02:00",
    })

    # A fresh repository object proves data is on disk, not process memory.
    summary = CalorieTracker(path).day_summary("2026-09-08")
    assert path.exists()
    assert summary["total_calories"] == 1150
    assert summary["remaining_calories"] == 1050
    assert summary["entries"][0]["id"] == first["id"]
    assert summary["entries"][0]["description"] == "oatmeal with berries"


def test_week_and_progress_include_empty_days_and_checkin(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    tracker.set_goal({"daily_calories": 2000, "effective_from": "2026-09-01"})
    tracker.add_entry({"calories": 1800, "description": "Monday meals", "occurred_at": "2026-09-07T18:00:00+02:00"})
    tracker.add_entry({"calories": 2200, "description": "Tuesday meals", "occurred_at": "2026-09-08T18:00:00+02:00"})
    tracker.record_checkin({"week_start": "2026-09-09", "weight_kg": 76.4, "note": "Mostly on plan"})

    week = tracker.week_summary("2026-09-09")  # normalises to Monday
    assert week["week_start"] == "2026-09-07"
    assert week["tracked_days"] == 2
    assert week["total_calories"] == 4000
    assert week["target_calories"] == 14000
    assert week["remaining_calories"] == 10000

    progress = tracker.progress(weeks=2, ending_on="2026-09-13")
    assert [item["week_start"] for item in progress["weeks"]] == ["2026-08-31", "2026-09-07"]
    assert len(progress["checkins"]) == 1
    assert progress["checkins"][0]["week_start"] == "2026-09-07"
    assert progress["checkins"][0]["weight_kg"] == 76.4
    assert progress["checkins"][0]["note"] == "Mostly on plan"
    assert progress["checkins"][0]["created_at"]


def test_tracker_rejects_unsafe_or_ambiguous_values(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    for payload in (
        {"calories": True, "description": "bad"},
        {"calories": 0, "description": "bad"},
        {"calories": 100, "description": ""},
        {"calories": 100, "description": "ok", "occurred_at": "not-a-date"},
    ):
        try:
            tracker.add_entry(payload)
        except CalorieValidationError:
            pass
        else:
            raise AssertionError("invalid calorie entry was accepted")


def test_calorie_api_end_to_end_and_input_validation(no_token, server_mod, client, monkeypatch):
    monkeypatch.setitem(server_mod.CFG, "calories", {})
    bad = client.post("/api/calories/entries", json={"calories": "400", "description": "toast"})
    assert bad.status_code == 400
    assert "integer" in bad.json()["error"]

    goal = client.put("/api/calories/goal", json={"daily_calories": 2100, "effective_from": "2026-09-07"})
    assert goal.status_code == 200
    entry = client.post("/api/calories/entries", json={
        "calories": 500, "description": "toast", "occurred_at": "2026-09-09T09:00:00+02:00",
    })
    assert entry.status_code == 201
    saved_id = entry.json()["entry"]["id"]

    day = client.get("/api/calories/days/2026-09-09")
    assert day.status_code == 200
    assert day.json()["total_calories"] == 500
    assert day.json()["remaining_calories"] == 1600
    assert client.delete(f"/api/calories/entries/{saved_id}").json()["deleted"] is True
    assert client.get("/api/calories/progress?weeks=not-a-number").status_code == 400


def test_calorie_api_requires_existing_token(with_token, client):
    response = client.post("/api/calories/entries", json={"calories": 100, "description": "tea"})
    assert response.status_code == 401


def test_tracker_merges_sugar_and_activity_into_calorie_balance(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    tracker.add_entry({
        "calories": 450, "description": "oatmeal with berries", "sugar_g": 18.5,
        "occurred_at": "2026-09-08T08:15:00+02:00",
    })
    tracker.record_activity({
        "day": "2026-09-08", "steps": 8421, "active_energy_kcal": 320, "dietary_sugar_g": 5,
    })

    summary = tracker.day_summary("2026-09-08")
    assert summary["steps"] == 8421
    assert summary["activity_calories"] == 320
    assert summary["net_calories"] == 130          # 450 consumed - 320 burned
    assert summary["total_sugar_g"] == 23.5         # 18.5 logged + 5 HealthKit-synced

    # Re-syncing the same day upserts rather than duplicating the row.
    tracker.record_activity({"day": "2026-09-08", "steps": 9000})
    updated = tracker.activity_for_day(date(2026, 9, 8))
    assert updated["steps"] == 9000


def test_day_summary_omits_activity_fields_when_nothing_synced(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    tracker.add_entry({"calories": 300, "description": "toast"})

    summary = tracker.day_summary(date.today())
    assert summary["steps"] is None
    assert summary["activity_calories"] is None
    assert summary["net_calories"] is None
    assert summary["total_sugar_g"] is None


def test_record_activity_rejects_empty_or_unsafe_payloads(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    for payload in (
        {"day": "2026-09-08"},
        {"day": "2026-09-08", "steps": -1},
        {"day": "2026-09-08", "active_energy_kcal": 999_999},
        {"day": "not-a-date", "steps": 100},
    ):
        try:
            tracker.record_activity(payload)
        except CalorieValidationError:
            pass
        else:
            raise AssertionError("invalid activity payload was accepted")


def test_activity_sync_api_end_to_end_and_requires_token(no_token, server_mod, client, monkeypatch):
    monkeypatch.setitem(server_mod.CFG, "calories", {})
    put = client.put("/api/activity/days/2026-09-09", json={
        "steps": 6200, "active_energy_kcal": 250, "dietary_sugar_g": 12,
    })
    assert put.status_code == 200
    assert put.json()["activity"]["steps"] == 6200

    bad = client.put("/api/activity/days/2026-09-09", json={})
    assert bad.status_code == 400

    day = client.get("/api/calories/days/2026-09-09")
    assert day.json()["steps"] == 6200
    assert day.json()["activity_calories"] == 250


def test_activity_sync_api_requires_existing_token(with_token, client):
    response = client.put("/api/activity/days/2026-09-09", json={"steps": 100})
    assert response.status_code == 401
