"""Five-stage pipeline E2E without a real LLM or Temporal server."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from cardio import llm
from cardio.gateway import _SqliteCache
from cardio.pipeline import STAGE_ORDER, run_pipeline


@pytest.fixture()
def fake_model(monkeypatch, tmp_path):
    calls = []
    responses = {
        "extraction": {"name": "Test Person", "company": "Sample Co", "summary": "observed"},
        "research": {"summary": "inference", "suggested_sources": ["company website"]},
        "synthesis": {"summary": "profile", "intent_score": 0.4},
        "strategy": {"summary": "next steps", "next_steps": ["contact buyer"]},
        "critique": {"summary": "needs verification", "passed": False,
                     "risk_alerts": ["evidence not verified"]},
    }
    stage_markers = {
        "提取官": "extraction",
        "调研员": "research",
        "画像师": "synthesis",
        "谋士": "strategy",
        "审官": "critique",
    }

    class Client:
        def __init__(self):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create)
            )

        async def create(self, *, model, messages, **kwargs):
            prompt = messages[0]["content"]
            stage = next((v for k, v in stage_markers.items() if k in prompt), None)
            assert stage is not None, "unrecognized stage prompt"
            calls.append((stage, model))
            response = json.dumps(responses[stage], ensure_ascii=False)
            if stage == "research":
                response = chr(96) * 3 + "json\n" + response + "\n" + chr(96) * 3
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=response))]
            )

        async def close(self):
            pass

    monkeypatch.setattr(llm._gateway, "_client", lambda base, key: Client())
    monkeypatch.setattr(
        llm._gateway, "_cache", _SqliteCache(str(tmp_path / "cache.sqlite"))
    )
    return calls


def test_pipeline_runs_five_distinct_real_functions(fake_model):
    events = []

    async def on_progress(stage, data):
        events.append((stage, data))

    out = asyncio.run(
        run_pipeline(
            "Test Person from Sample Co", on_progress=on_progress,
            provider={"api_key": "synthetic-only", "model": "selected-provider-model"},
        )
    )
    assert [stage for stage, _ in fake_model] == STAGE_ORDER
    assert all(model == "selected-provider-model" for _, model in fake_model)
    assert out["profile"]["name"] == "Test Person"
    assert set(out["agent_reports"]) == set(STAGE_ORDER)
    assert out["agent_reports"]["research"]["details"]["summary"] == "inference"
    assert out["agent_reports"]["critique"]["details"]["passed"] is False
    assert [stage for stage, _ in events].count("stage_done") == 5
    assert events[-1][0] == "complete"
