"""Cardio LLM 每日配额测试 — 不调 LLM（仅打桩客户端构造）。

配额门位于 client_for 的平台分支内；测试只替换 get_client/AsyncOpenAI 构造，
保留 client_for 真实逻辑（含配额门、BYOK 跳过）。缓存 DB 每测试隔离到 tmp_path，
避免跨测试缓存串扰。

运行（仓库根）：
    venv/bin/python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.getenv("OPENCLAW_SHARED_DIR", "/opt/shared"))

import cardio.config as _cardio_config  # noqa: E402
from cardio import llm  # noqa: E402
import llm_quota  # noqa: E402


class _Msg:
    content = "fake-llm-response"


class _Choice:
    message = _Msg()


class _Resp:
    choices = [_Choice()]


class _FakeClient:
    """记录 create 调用并返回假响应（chat 与 activities 两条路径都经 client_for）。"""

    def __init__(self):
        self.calls: list = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp()


@pytest.fixture()
def fake_client(monkeypatch):
    """只打桩客户端构造；client_for 的真实逻辑（含配额门）照常执行。"""
    client = _FakeClient()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr(llm, "AsyncOpenAI", lambda **kwargs: client)
    return client


@pytest.fixture()
def quota_db(monkeypatch, tmp_path):
    """配额库 + 缓存库双隔离到 tmp_path，避免跨测试串扰。"""
    db = str(tmp_path / "llm_quota.db")
    monkeypatch.setenv("CARDIO_QUOTA_DB", db)
    monkeypatch.setattr(_cardio_config, "DB_PATH", str(tmp_path / "cardio.db"))
    return db


def _exhaust(db: str, scope: str, limit: int = 3) -> None:
    for _ in range(limit):
        assert llm_quota.allow(db, scope, limit=limit)


def _chat(**kwargs):
    return asyncio.run(llm.chat([{"role": "user", "content": "hi"}], **kwargs))


def test_platform_quota_exhausted_raises(fake_client, quota_db):
    llm.set_scope("u1")
    _exhaust(quota_db, "u1")
    with pytest.raises(llm.LLMQuotaExceeded):
        _chat()
    assert fake_client.calls == []


def test_within_quota_passes(fake_client, quota_db):
    llm.set_scope("u1")
    assert _chat() == "fake-llm-response"
    assert len(fake_client.calls) == 1


def test_byok_skips_quota(fake_client, quota_db):
    llm.set_scope("u1")
    _exhaust(quota_db, "u1")
    out = _chat(provider={"api_key": "user-own-key", "base_url": "https://byok.example/v1", "model": "m"})
    assert out == "fake-llm-response"
    assert len(fake_client.calls) == 1


def test_scope_isolation(fake_client, quota_db):
    llm.set_scope("u1")
    _exhaust(quota_db, "u1")
    llm.set_scope("u2")
    assert _chat() == "fake-llm-response"


def test_cache_hit_does_not_consume_quota(fake_client, quota_db):
    llm.set_scope("u1")
    _chat()
    _chat()
    assert len(fake_client.calls) == 1  # 第二次命中缓存
    assert llm_quota.used(quota_db, "u1") == 1  # 缓存命中不计量


def test_quota_env_unlimited(fake_client, quota_db, monkeypatch):
    monkeypatch.setenv("LLM_QUOTA_LIMIT", "0")
    llm.set_scope("u1")
    for i in range(5):
        out = asyncio.run(llm.chat([{"role": "user", "content": f"m{i}"}], stream=False))
        assert out == "fake-llm-response"
    assert len(fake_client.calls) == 5
