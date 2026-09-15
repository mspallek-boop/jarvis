"""Offline tests for the durable local calorie diary and its FastAPI surface."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import sys

from calorie_tracker import CalorieTracker, CalorieValidationError

PLUGIN_PARENT = Path(__file__).resolve().parent.parent / "hermes-plugin"
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))
from jarvis_calories.report import format_daily_balance
from jarvis_calories import tools as calorie_tools


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


def test_tracker_totals_optional_macros_without_changing_existing_entries(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    tracker.add_entry({
        "calories": 540, "description": "vegetable pasta", "protein_g": 22,
        "fat_g": 14, "carbohydrates_g": 75, "sugar_g": 6.5,
        "occurred_at": "2026-09-08T18:15:00+02:00",
    })
    tracker.add_entry({"calories": 100, "description": "tea", "occurred_at": "2026-09-08T20:00:00+02:00"})

    summary = tracker.day_summary("2026-09-08")
    assert summary["total_protein_g"] == 22
    assert summary["total_fat_g"] == 14
    assert summary["total_carbohydrates_g"] == 75
    assert summary["entries"][1]["protein_g"] is None


def test_tracker_migrates_existing_diary_without_losing_entries(tmp_path):
    path = tmp_path / "calories.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE calorie_entries (
            id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, day TEXT NOT NULL,
            calories INTEGER NOT NULL, description TEXT NOT NULL, meal TEXT,
            sugar_g REAL, created_at TEXT NOT NULL)""")
        conn.execute("""INSERT INTO calorie_entries
            VALUES ('old-entry', '2026-09-08T08:00:00+02:00', '2026-09-08', 450,
                    'existing breakfast', 'breakfast', 8.5, '2026-09-08T08:00:00+02:00')""")

    summary = CalorieTracker(path).day_summary("2026-09-08")
    assert summary["entries"][0]["description"] == "existing breakfast"
    assert summary["entries"][0]["protein_g"] is None
    assert summary["total_sugar_g"] == 8.5


def test_targets_follow_from_calorie_goal_and_goal_weight():
    from calorie_tracker import nutrient_targets
    # 2000 kcal, 70 kg: protein 2 g/kg, fat 30 %, carbs the rest, sugar max 10 %.
    assert nutrient_targets(2000, 70) == {
        "calories": 2000, "protein_g": 140, "carbohydrates_g": 209, "fat_g": 67, "sugar_g": 50}
    # Without a goal weight protein falls back to 25 % of the calories.
    assert nutrient_targets(2000, None)["protein_g"] == 125


def test_day_summary_puts_ist_next_to_soll_with_a_verdict(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    goal = tracker.set_goal({"daily_calories": 2000, "goal_weight_kg": 70, "effective_from": "2026-09-01"})
    assert goal["targets"]["protein_g"] == 140
    tracker.add_entry({"calories": 1500, "description": "pasta", "protein_g": 60, "fat_g": 80,
                       "carbohydrates_g": 150, "sugar_g": 20, "occurred_at": "2026-09-08T12:00:00+02:00"})

    rows = {row["key"]: row for row in tracker.day_summary("2026-09-08")["nutrients"]}
    assert (rows["calories"]["actual"], rows["calories"]["target"], rows["calories"]["status"]) == (1500, 2000, "ok")
    assert rows["protein_g"]["status"] == "under"
    assert rows["fat_g"]["status"] == "over"
    assert rows["sugar_g"]["status"] == "ok"

    # A second entry without macros makes the Ist a lower bound: no "ok" for limits any more.
    tracker.add_entry({"calories": 100, "description": "juice", "occurred_at": "2026-09-08T15:00:00+02:00"})
    rows = {row["key"]: row for row in tracker.day_summary("2026-09-08")["nutrients"]}
    assert rows["sugar_g"]["status"] == "incomplete"
    assert rows["fat_g"]["status"] == "over"
    assert rows["protein_g"]["status"] == "incomplete"


def test_changing_only_calories_keeps_the_goal_weight(tmp_path):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    tracker.set_goal({"daily_calories": 2000, "goal_weight_kg": 70, "effective_from": "2026-09-01"})
    changed = tracker.set_goal({"daily_calories": 1800, "effective_from": "2026-09-10"})
    assert changed["goal_weight_kg"] == 70
    assert tracker.day_summary("2026-09-11")["targets"]["calories"] == 1800


def test_goal_weight_column_is_added_to_an_existing_diary(tmp_path):
    path = tmp_path / "calories.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE calorie_goals (effective_from TEXT PRIMARY KEY,
            daily_calories INTEGER NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO calorie_goals VALUES ('2026-09-01', 2000, '2026-09-01T00:00:00+02:00')")
    summary = CalorieTracker(path).day_summary("2026-09-08")
    assert summary["target_calories"] == 2000 and summary["goal_weight_kg"] is None


def _report_summary(tmp_path, **goal):
    tracker = CalorieTracker(tmp_path / "calories.sqlite3")
    if goal:
        tracker.set_goal({"effective_from": "2026-09-01", **goal})
    return tracker


def test_daily_balance_report_lists_every_nutrient_as_ist_and_soll(tmp_path):
    tracker = _report_summary(tmp_path, daily_calories=2000, goal_weight_kg=70)
    tracker.add_entry({"calories": 1890, "description": "Skyr", "protein_g": 115.8, "fat_g": 70.9,
                       "carbohydrates_g": 195.6, "sugar_g": 69, "occurred_at": "2026-09-09T12:00:00+02:00"})
    tracker.record_activity({"day": "2026-09-09", "steps": 8421, "active_energy_kcal": 320})
    report = format_daily_balance(tracker.day_summary("2026-09-09"))

    assert report.startswith("🍽️ *Tagesbilanz · Mi 09.09.2026*")
    assert ("*Nährwerte · Ist / Soll*\n"
            "🔥 Kalorien: *1.890* / max. 2.000 kcal  ✅ 110 kcal übrig\n"
            "🥩 Eiweiß: *115,8* / mind. 140 g  ⚠️ 24,2 g fehlen\n"
            "🍞 Kohlenhydrate: *195,6* / max. 209 g  ✅ 13,4 g übrig\n"
            "🧈 Fett: *70,9* / max. 67 g  ⚠️ 3,9 g zu viel\n"
            "🍬 Zucker: *69* / max. 50 g  ⚠️ 19 g zu viel") in report
    assert "⚠️ Daneben: Eiweiß, Fett, Zucker" in report
    assert "_Soll aus deinem Ziel: 2.000 kcal/Tag · Zielgewicht 70 kg_" in report
    assert "*Aktivität*\n🏃 Aktivität 320 kcal · Netto 1.570 kcal\n👟 8.421 Schritte" in report
    assert report.endswith("*Erfasst (1)*\n• Skyr")


def test_daily_balance_report_all_in_soll_and_missing_values(tmp_path):
    tracker = _report_summary(tmp_path, daily_calories=2000, goal_weight_kg=70)
    tracker.add_entry({"calories": 1900, "description": "Bowl", "protein_g": 150, "fat_g": 60,
                       "carbohydrates_g": 200, "sugar_g": 30, "occurred_at": "2026-09-09T12:00:00+02:00"})
    assert "✅ Alles im Soll — gut gegessen" in format_daily_balance(tracker.day_summary("2026-09-09"))

    tracker.add_entry({"calories": 300, "description": "tea", "occurred_at": "2026-09-10T12:00:00+02:00"})
    report = format_daily_balance(tracker.day_summary("2026-09-10"))
    assert "🥩 Eiweiß: nicht erfasst / mind. 140 g" in report
    assert "*Aktivität*" not in report


def test_daily_balance_report_without_goal_says_there_is_no_soll(tmp_path):
    tracker = _report_summary(tmp_path)
    tracker.add_entry({"calories": 300, "description": "tea", "protein_g": 2,
                       "occurred_at": "2026-09-10T12:00:00+02:00"})
    report = format_daily_balance(tracker.day_summary("2026-09-10"))
    assert "🥩 Eiweiß: *2* g · kein Soll" in report
    assert "_Kein Ziel gesetzt — deshalb kein Soll._" in report
    assert report.endswith("*Erfasst (1)*\n• tea")


def test_daily_report_tool_returns_the_formatted_message(monkeypatch, tmp_path):
    import json
    tracker = _report_summary(tmp_path, daily_calories=2000)
    tracker.add_entry({"calories": 300, "description": "tea", "occurred_at": "2026-09-09T12:00:00+02:00"})
    summary = json.dumps(tracker.day_summary("2026-09-09"))
    monkeypatch.setattr(calorie_tools, "_request", lambda *args, **kwargs: summary)

    report = calorie_tools.calories_daily_report({"date": "2026-09-09"})
    assert report.startswith("🍽️ *Tagesbilanz · Mi 09.09.2026*")
    assert "🔥 Kalorien: *300* / max. 2.000 kcal  ✅ 1.700 kcal übrig" in report
    assert report.endswith("*Erfasst (1)*\n• tea")


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
