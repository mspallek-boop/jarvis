"""The evening balance goes out once, in the evening — never twice, never next morning."""
import datetime
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "calorie_balance", Path(__file__).resolve().parents[1] / "scripts/jarvis-calorie-balance.py")
balance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(balance)

EVENING = datetime.datetime(2026, 9, 10, 22, 0)


def test_not_before_ten():
    assert not balance.due(EVENING - datetime.timedelta(minutes=1), "")


def test_at_ten_and_later_that_evening():
    assert balance.due(EVENING, "2026-09-09")
    assert balance.due(EVENING.replace(hour=23, minute=59), "")


def test_only_once_per_day():
    assert not balance.due(EVENING.replace(hour=22, minute=30), "2026-09-10")


def test_a_wake_next_morning_does_not_send_last_night():
    """launchd runs a missed 22:00 on wake; at 08:00 that must be a no-op."""
    assert not balance.due(datetime.datetime(2026, 9, 11, 8, 0), "2026-09-09")


def test_the_sent_day_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(balance, "STATE", tmp_path / "state.json")
    assert balance.last_sent() == ""
    balance.mark_sent("2026-09-10")
    assert balance.last_sent() == "2026-09-10"


def test_the_text_comes_from_the_plugin_report(monkeypatch):
    """Same generator as the Hermes tool, so the message is what the tool returns."""
    monkeypatch.setattr(balance, "REPORT",
                        Path(__file__).resolve().parents[1] / "hermes-plugin/jarvis_calories/report.py")
    text = balance.format_balance({"date": "2026-09-10", "total_calories": 566, "entries": [],
                                   "entry_count": 0, "total_sugar_g": 19.6})
    assert text.startswith("*Tagesbilanz – Donnerstag, 10. September 2026*")
    assert "566 kcal" in text and "nicht erfasst" in text
