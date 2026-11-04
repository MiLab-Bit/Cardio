"""Runtime boundary regressions: quota isolation, fail-closed accounting, JSON parsing."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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



def test_live_streams_hold_semaphore_and_close_clients(tmp_path):
    async def scenario():
        gateway = Gateway(
            platform_base_url="http://127.0.0.1:9/v1",
            platform_api_key="offline-test",
            default_model="mock",
            quota_db=str(tmp_path / "quota.sqlite"),
            cache_db=str(tmp_path / "cache.sqlite"),
            max_concurrency=1,
        )
        gateway._quota.limit = None
        reached_first = asyncio.Event()
        release = asyncio.Event()
        started = []
        closed = []

        class Client:
            def __init__(self):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=self.create)
                )

            async def create(self, **kw):
                started.append(kw["model"])
                reached_first.set()

                async def chunks():
                    yield SimpleNamespace(choices=[
                        SimpleNamespace(delta=SimpleNamespace(content="x"))
                    ])
                    await release.wait()

                return chunks()

            async def close(self):
                closed.append(True)

        gateway._client = lambda base, key: Client()

        async def collect(text):
            stream = await gateway.chat(
                [{"role": "user", "content": text}], stream=True, scope="test"
            )
            return [token async for token in stream]

        first = asyncio.create_task(collect("one"))
        await reached_first.wait()
        second = asyncio.create_task(collect("two"))
        await asyncio.sleep(0.02)
        assert started == ["mock"], "second stream bypassed concurrency limit"
        release.set()
        results = await asyncio.gather(first, second)
        assert results == [["x"], ["x"]]
        assert len(started) == len(closed) == 2

    asyncio.run(scenario())
