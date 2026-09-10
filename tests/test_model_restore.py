"""The Tuesday switch-back may only touch the config blocks it wrote itself."""
import datetime
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "model_restore", Path(__file__).resolve().parents[1] / "scripts/jarvis-model-restore.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)

LIVE = (restore.TEMP_BLOCK + "providers:\n  ollama-launch:\n    name: Ollama\n"
        + restore.TEMP_FALLBACK + "mcp_servers: {}\n")


def test_the_temporary_blocks_are_swapped_back():
    out = restore.restored_config(LIVE)
    assert out.startswith(restore.CODEX_BLOCK)
    assert restore.CODEX_FALLBACK in out and "longcat" not in out
    assert "providers:\n  ollama-launch:\n    name: Ollama\n" in out


def test_a_config_someone_else_changed_is_left_alone():
    assert restore.restored_config(LIVE.replace("poolside/laguna-s-2.1:free", "anderes-modell")) is None
    assert restore.restored_config(restore.CODEX_BLOCK) is None


def test_a_changed_fallback_alone_does_not_block_the_primary():
    out = restore.restored_config(restore.TEMP_BLOCK + "fallback_model:\n  provider: xai\n  model: grok\n")
    assert out.startswith(restore.CODEX_BLOCK) and "grok" in out


def test_nothing_happens_before_the_quota_returns():
    assert not restore.due(datetime.datetime(2026, 9, 15, 7, 14))
    assert restore.due(datetime.datetime(2026, 9, 15, 7, 15))


def test_only_the_free_stand_ins_count_as_pinned():
    assert "poolside/laguna-s-2.1:free".startswith(restore.FREE_PREFIXES)
    assert "meituan/longcat-2.0:free".startswith(restore.FREE_PREFIXES)
    assert not "gpt-5.6-luna".startswith(restore.FREE_PREFIXES)
