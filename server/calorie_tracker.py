"""Local, durable calorie tracking backed by SQLite.

The tracker deliberately has no cloud dependency.  A new connection is opened
per operation so it is safe to use from FastAPI worker threads and survives a
server restart.  Calendar dates are derived from the timestamp supplied by the
caller (or the server's local timezone when omitted).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


class CalorieValidationError(ValueError):
    """Raised when a tracker request cannot be represented safely."""


def _parse_date(value: object, field: str = "date") -> date:
    if not isinstance(value, str):
        raise CalorieValidationError(f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CalorieValidationError(f"{field} must be an ISO date (YYYY-MM-DD)") from exc


def _parse_timestamp(value: object | None) -> datetime:
    if value in (None, ""):
        return datetime.now().astimezone()
    if not isinstance(value, str):
        raise CalorieValidationError("occurred_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CalorieValidationError("occurred_at must be an ISO-8601 timestamp") from exc
    # Naive values are intentionally local: this is a personal daily diary.
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()


def _text(value: object, field: str, maximum: int, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise CalorieValidationError(f"{field} must be text")
    cleaned = " ".join(value.split())
    if required and not cleaned:
        raise CalorieValidationError(f"{field} is required")
    if len(cleaned) > maximum:
        raise CalorieValidationError(f"{field} must be at most {maximum} characters")
    return cleaned or None


def _calories(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20_000:
        raise CalorieValidationError("calories must be an integer between 1 and 20000")
    return value


def _optional_number(value: object, field: str, minimum: float, maximum: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
        raise CalorieValidationError(f"{field} must be a number between {minimum} and {maximum}")
    return float(value)


def _optional_int(value: object, field: str, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CalorieValidationError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


class CalorieTracker:
    """SQLite repository for calorie entries, targets and weekly check-ins."""

    def __init__(self, path: Path):
        self.path = path

    def _connection(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS calorie_entries (
                    id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    day TEXT NOT NULL,
                    calories INTEGER NOT NULL CHECK(calories > 0),
                    description TEXT NOT NULL,
                    meal TEXT,
                    sugar_g REAL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS calorie_entries_day_idx ON calorie_entries(day, occurred_at);
                CREATE TABLE IF NOT EXISTS calorie_goals (
                    effective_from TEXT PRIMARY KEY,
                    daily_calories INTEGER NOT NULL CHECK(daily_calories > 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calorie_weekly_checkins (
                    week_start TEXT PRIMARY KEY,
                    weight_kg REAL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_summaries (
                    day TEXT PRIMARY KEY,
                    steps INTEGER,
                    active_energy_kcal REAL,
                    dietary_sugar_g REAL,
                    source TEXT NOT NULL DEFAULT 'healthkit',
                    synced_at TEXT NOT NULL
                );
                """
            )
            # A diary created before sugar_g existed lacks the column; the
            # CREATE TABLE above only applies to a brand-new file.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(calorie_entries)")}
            if "sugar_g" not in existing:
                conn.execute("ALTER TABLE calorie_entries ADD COLUMN sugar_g REAL")

    @staticmethod
    def _entry(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "occurred_at": row["occurred_at"], "day": row["day"],
            "calories": row["calories"], "description": row["description"], "meal": row["meal"],
            "sugar_g": row["sugar_g"], "created_at": row["created_at"],
        }

    def add_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        occurred = _parse_timestamp(payload.get("occurred_at"))
        entry = {
            "id": str(uuid.uuid4()),
            "occurred_at": occurred.isoformat(timespec="seconds"),
            "day": occurred.date().isoformat(),
            "calories": _calories(payload.get("calories")),
            "description": _text(payload.get("description"), "description", 250, required=True),
            "meal": _text(payload.get("meal"), "meal", 40),
            "sugar_g": _optional_number(payload.get("sugar_g"), "sugar_g", 0, 2000),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.initialize()
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO calorie_entries
                   (id, occurred_at, day, calories, description, meal, sugar_g, created_at)
                   VALUES (:id, :occurred_at, :day, :calories, :description, :meal, :sugar_g, :created_at)""",
                entry,
            )
        return entry

    def delete_entry(self, entry_id: str) -> bool:
        if not isinstance(entry_id, str) or not entry_id:
            raise CalorieValidationError("entry id is required")
        self.initialize()
        with self._connection() as conn:
            return conn.execute("DELETE FROM calorie_entries WHERE id = ?", (entry_id,)).rowcount == 1

    def set_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        effective = _parse_date(payload.get("effective_from") or date.today().isoformat(), "effective_from")
        target = _calories(payload.get("daily_calories"))
        saved = {
            "effective_from": effective.isoformat(), "daily_calories": target,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.initialize()
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO calorie_goals (effective_from, daily_calories, created_at)
                   VALUES (:effective_from, :daily_calories, :created_at)
                   ON CONFLICT(effective_from) DO UPDATE SET
                     daily_calories=excluded.daily_calories, created_at=excluded.created_at""",
                saved,
            )
        return saved

    def goal_for(self, on_day: date) -> int | None:
        self.initialize()
        with self._connection() as conn:
            row = conn.execute(
                """SELECT daily_calories FROM calorie_goals
                   WHERE effective_from <= ? ORDER BY effective_from DESC LIMIT 1""", (on_day.isoformat(),)
            ).fetchone()
        return int(row["daily_calories"]) if row else None

    def record_activity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Upsert one day's HealthKit-sourced activity aggregate.

        Intentionally data-sparse: only the daily totals needed for a calorie
        balance (steps, active energy burned, dietary sugar already logged in
        Apple Health elsewhere) are accepted, never minute-by-minute samples,
        workouts, heart rate or sleep data.
        """
        day = _parse_date(payload.get("day") or date.today().isoformat())
        steps = _optional_int(payload.get("steps"), "steps", 0, 200_000)
        active_energy = _optional_number(payload.get("active_energy_kcal"), "active_energy_kcal", 0, 20_000)
        dietary_sugar = _optional_number(payload.get("dietary_sugar_g"), "dietary_sugar_g", 0, 2000)
        if steps is None and active_energy is None and dietary_sugar is None:
            raise CalorieValidationError("at least one of steps, active_energy_kcal, dietary_sugar_g is required")
        saved = {
            "day": day.isoformat(), "steps": steps, "active_energy_kcal": active_energy,
            "dietary_sugar_g": dietary_sugar,
            "source": _text(payload.get("source"), "source", 40) or "healthkit",
            "synced_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.initialize()
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO activity_summaries
                   (day, steps, active_energy_kcal, dietary_sugar_g, source, synced_at)
                   VALUES (:day, :steps, :active_energy_kcal, :dietary_sugar_g, :source, :synced_at)
                   ON CONFLICT(day) DO UPDATE SET
                     steps=excluded.steps, active_energy_kcal=excluded.active_energy_kcal,
                     dietary_sugar_g=excluded.dietary_sugar_g, source=excluded.source,
                     synced_at=excluded.synced_at""",
                saved,
            )
        return saved

    def activity_for_day(self, day: date) -> dict[str, Any] | None:
        self.initialize()
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM activity_summaries WHERE day = ?", (day.isoformat(),)).fetchone()
        if row is None:
            return None
        return {
            "day": row["day"], "steps": row["steps"], "active_energy_kcal": row["active_energy_kcal"],
            "dietary_sugar_g": row["dietary_sugar_g"], "source": row["source"], "synced_at": row["synced_at"],
        }

    def day_summary(self, day_value: str | date) -> dict[str, Any]:
        day = _parse_date(day_value) if isinstance(day_value, str) else day_value
        self.initialize()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM calorie_entries WHERE day = ? ORDER BY occurred_at, created_at", (day.isoformat(),)
            ).fetchall()
        entries = [self._entry(row) for row in rows]
        total = sum(entry["calories"] for entry in entries)
        target = self.goal_for(day)
        activity = self.activity_for_day(day)
        logged_sugar = sum(entry["sugar_g"] for entry in entries if entry["sugar_g"] is not None)
        synced_sugar = activity["dietary_sugar_g"] if activity and activity["dietary_sugar_g"] is not None else None
        has_sugar = bool(entries and any(e["sugar_g"] is not None for e in entries)) or synced_sugar is not None
        activity_calories = activity["active_energy_kcal"] if activity else None
        return {
            "date": day.isoformat(), "total_calories": total, "target_calories": target,
            "remaining_calories": target - total if target is not None else None,
            "entry_count": len(entries), "entries": entries,
            "steps": activity["steps"] if activity else None,
            "activity_calories": activity_calories,
            "net_calories": total - activity_calories if activity_calories is not None else None,
            "total_sugar_g": round(logged_sugar + (synced_sugar or 0), 1) if has_sugar else None,
        }

    def week_summary(self, week_value: str | date) -> dict[str, Any]:
        supplied = _parse_date(week_value, "week_start") if isinstance(week_value, str) else week_value
        start = supplied - timedelta(days=supplied.weekday())
        days = [self.day_summary(start + timedelta(days=offset)) for offset in range(7)]
        total = sum(day["total_calories"] for day in days)
        tracked = [day for day in days if day["entry_count"]]
        targets = [day["target_calories"] for day in days if day["target_calories"] is not None]
        target_total = sum(targets) if len(targets) == 7 else None
        return {
            "week_start": start.isoformat(), "week_end": (start + timedelta(days=6)).isoformat(),
            "total_calories": total, "average_daily_calories": round(total / len(tracked), 1) if tracked else None,
            "tracked_days": len(tracked), "target_calories": target_total,
            "remaining_calories": target_total - total if target_total is not None else None,
            "days": days,
        }

    def record_checkin(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_day = _parse_date(payload.get("week_start") or date.today().isoformat(), "week_start")
        start = raw_day - timedelta(days=raw_day.weekday())
        weight = payload.get("weight_kg")
        if weight is not None and (isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 20 <= float(weight) <= 500):
            raise CalorieValidationError("weight_kg must be a number between 20 and 500")
        saved = {
            "week_start": start.isoformat(), "weight_kg": float(weight) if weight is not None else None,
            "note": _text(payload.get("note"), "note", 1000),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        self.initialize()
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO calorie_weekly_checkins (week_start, weight_kg, note, created_at)
                   VALUES (:week_start, :weight_kg, :note, :created_at)
                   ON CONFLICT(week_start) DO UPDATE SET
                     weight_kg=excluded.weight_kg, note=excluded.note, created_at=excluded.created_at""",
                saved,
            )
        return saved

    def progress(self, weeks: int = 8, ending_on: str | None = None) -> dict[str, Any]:
        if isinstance(weeks, bool) or not isinstance(weeks, int) or not 1 <= weeks <= 52:
            raise CalorieValidationError("weeks must be an integer between 1 and 52")
        ending = _parse_date(ending_on, "ending_on") if ending_on else date.today()
        last_start = ending - timedelta(days=ending.weekday())
        starts = [last_start - timedelta(days=7 * offset) for offset in range(weeks - 1, -1, -1)]
        summaries = [self.week_summary(start) for start in starts]
        self.initialize()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM calorie_weekly_checkins WHERE week_start >= ? AND week_start <= ? ORDER BY week_start",
                (starts[0].isoformat(), starts[-1].isoformat()),
            ).fetchall()
        checkins = [{"week_start": row["week_start"], "weight_kg": row["weight_kg"],
                     "note": row["note"], "created_at": row["created_at"]} for row in rows]
        return {"weeks": summaries, "checkins": checkins, "from": starts[0].isoformat(), "to": ending.isoformat()}
