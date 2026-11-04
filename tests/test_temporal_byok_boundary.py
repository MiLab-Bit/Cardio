"""Temporal BYOK boundary and durable Cardio analysis contract (offline)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, fields

import pytest

from cardio import store
from cardio.temporal.common import AnalyzeInput


def test_workflow_input_cannot_accept_plaintext_provider():
    names = {f.name for f in fields(AnalyzeInput)}
    assert names == {"raw_text", "raw_type", "provider_id", "owner", "contact_id"}
    payload = asdict(AnalyzeInput(raw_text="synthetic", owner="user1", provider_id="p123"))
    assert not ({"provider", "api_key", "api_key_enc", "base_url"} & payload.keys())
    assert "secret" not in json.dumps(payload)
    with pytest.raises(TypeError):
        AnalyzeInput(raw_text="x", provider={"api_key": "synthetic-secret"})


def test_provider_reference_is_owner_scoped_and_decrypts_only_in_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(store.config, "DB_PATH", str(tmp_path / "cardio.sqlite"))
    pid = store.create_model_provider(
        "owner-a", "BYOK", "openai", "synthetic-test-secret",
        "https://example.invalid/v1", "test-model", slot="text",
    )
    wrong_slot = store.create_model_provider(
        "owner-a", "Vision", "openai", "synthetic-test-mm-secret",
        "https://example.invalid/v1", "test-vision", slot="multimodal",
    )
    # ID lookup in the API must never decrypt the key.
    from cardio import crypto
    real_decrypt = crypto.decrypt

    def forbidden_decrypt(token):
        raise AssertionError("API lookup decrypted BYOK")

    monkeypatch.setattr(crypto, "decrypt", forbidden_decrypt)
    assert store.get_active_provider_id("owner-a", "text") == pid
    assert store.get_active_provider_id("owner-b", "text") is None
    monkeypatch.setattr(crypto, "decrypt", real_decrypt)

    provider = store.resolve_workflow_provider(pid, "owner-a")
    assert provider["api_key"] == "synthetic-test-secret"
    with pytest.raises(LookupError):
        store.resolve_workflow_provider(pid, "owner-b")
    with pytest.raises(LookupError):
        store.resolve_workflow_provider(wrong_slot, "owner-a")
    store.delete_model_provider(pid, "owner-a")
    with pytest.raises(LookupError):
        store.resolve_workflow_provider(pid, "owner-a")


def test_activity_resolves_secret_locally_and_result_does_not_contain_it(monkeypatch):
    from cardio import llm
    from cardio.temporal import activities

    observed = {}

    def resolver(pid, owner):
        assert pid == "p123"
        assert owner == "owner-a"
        return {"id": "p123", "api_key": "synthetic-test-secret", "model": "test-model"}

    async def fake_chat(messages, **kwargs):
        observed["provider"] = kwargs["provider"]
        observed["model"] = kwargs["model"]
        return '{"summary":"safe"}'

    monkeypatch.setattr(store, "resolve_workflow_provider", resolver)
    monkeypatch.setattr(llm, "chat", fake_chat)
    result = asyncio.run(activities.extraction_activity({
        "raw_text": "synthetic lead", "owner": "owner-a", "provider_id": "p123",
    }))
    assert result == {"summary": "safe"}
    assert observed["provider"]["api_key"] == "synthetic-test-secret"
    assert "synthetic-test-secret" not in json.dumps(result)


def test_idempotent_temporal_persistence(monkeypatch, tmp_path):
    from cardio.temporal.activities import persist_analysis_activity

    monkeypatch.setattr(store.config, "DB_PATH", str(tmp_path / "cardio.sqlite"))
    raw = {
        "owner": "owner-a", "input_text": "synthetic source",
        "analysis_id": "cardio-analyze-fixed",
        "contact_id": None,
        "results": {
            key: {"summary": key, "confidence": 0.8}
            for key in ("extraction", "research", "synthesis", "strategy", "critique")
        },
    }
    asyncio.run(persist_analysis_activity(raw))
    asyncio.run(persist_analysis_activity(raw))
    records = store.list_analyses("owner-a")
    assert len(records) == 1
    assert records[0]["id"] == "cardio-analyze-fixed"
    assert set(records[0]["result"]["agent_reports"]) == set(raw["results"])


def test_http_analysis_submits_only_provider_id_to_temporal(monkeypatch):
    from temporalio.client import Client

    from cardio import server

    submitted = []
    snapshot = {"status": "completed", "progress": [], "results": {},
                "result": {"profile": {}, "agent_reports": {}}}

    class FakeHandle:
        async def result(self):
            return snapshot

        async def query(self, query):
            return snapshot

    class FakeClient:
        async def start_workflow(self, method, inp, **kwargs):
            submitted.append(asdict(inp))
            return FakeHandle()

    async def connect(*args, **kwargs):
        return FakeClient()

    class FakeRequest:
        async def json(self):
            return {"text": "synthetic lead"}

    monkeypatch.setattr(Client, "connect", connect)
    monkeypatch.setattr(server, "resolve_owner", lambda req: "owner-a")
    monkeypatch.setattr(store, "get_active_provider_id", lambda owner, slot: "p123")

    async def scenario():
        response = await server.analyze(FakeRequest())
        frames = [frame async for frame in response.body_iterator]
        return "".join(frames)

    output = asyncio.run(scenario())
    assert submitted and submitted[0]["provider_id"] == "p123"
    assert not any(k in submitted[0] for k in ("provider", "api_key", "api_key_enc"))
    assert "\\n\\n" not in output
    assert "\n\n" in output
    assert '"type": "complete"' in output
