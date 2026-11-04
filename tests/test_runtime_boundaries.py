"""Runtime boundary regressions: quota isolation, fail-closed accounting, JSON parsing."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from cardio.gateway import Gateway, QuotaExceeded, QuotaGate
from cardio.llm import extract_json


def test_json_parser_recovers_original_pipeline_contract():
    fence = chr(96) * 3
    assert extract_json(fence + 'json\n{"ok":true}\n' + fence) == {"ok": True}
    assert extract_json('prefix {"stage":"research"} suffix') == {"stage": "research"}
    assert extract_json("not JSON") == {"raw": "not JSON"}


def test_cache_identity_isolated_by_owner_and_byok_key():
    messages = [{"role": "user", "content": "private company research"}]
    base = Gateway._cache_key("owner-a", None, "qwen", .2, 100, messages)
    other_owner = Gateway._cache_key("owner-b", None, "qwen", .2, 100, messages)
    byok1 = Gateway._cache_key("owner-a", {"api_key": "first-secret"}, "qwen", .2, 100, messages)
    byok2 = Gateway._cache_key("owner-a", {"api_key": "second-secret"}, "qwen", .2, 100, messages)
    assert len({base, other_owner, byok1, byok2}) == 4
    for key in (base, other_owner, byok1, byok2):
        assert "secret" not in key


def test_quota_storage_fails_closed(tmp_path):
    # A directory is not an SQLite database, so quota accounting must deny.
    gate = QuotaGate(str(tmp_path), limit=3)
    with pytest.raises(QuotaExceeded, match="storage unavailable"):
        gate.consume("owner")


def test_simultaneous_calls_do_not_exceed_daily_limit(tmp_path):
    gate = QuotaGate(str(tmp_path / "quota.sqlite"), limit=3)

    def attempt(_: int) -> bool:
        try:
            gate.consume("one-user")
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        admitted = list(executor.map(attempt, range(12)))
    assert sum(admitted) == 3
    assert gate.used("one-user") == 3


def test_temporal_worker_imports_without_openclaw_shared_runtime():
    from cardio.temporal.worker import _run
    assert callable(_run)
