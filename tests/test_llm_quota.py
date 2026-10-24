"""Cardio LLM 配额/缓存/BYOK 集成测试 — 不调 LLM（打桩 Gateway 客户端）。

cardio.llm 现已委托 hermes_core.gateway.Gateway；本测试只替换 Gateway 的
客户端构造与配额/缓存存储，验证 cardio.llm 这一层的配额门、BYOK 跳过、
缓存命中不计量行为（真实网关逻辑在 hermes_core 黄金测试中覆盖）。

运行（仓库根）：venv/bin/python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO)

from hermes_core.gateway import _SqliteCache  # noqa: E402
from hermes_core.quota import QuotaGate  # noqa: E402

from cardio import llm  # noqa: E402


class _Resp:
    def __init__(self):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content="fake-llm-response"))]


class _Completions:
    def __init__(self, client):
        self.client = client

    async def create(self, **kw):
        self.client.calls.append(kw)
        return _Resp()


class _Chat:
    def __init__(self, client):
        self.completions = _Completions(client)


class _FakeClient:
    def __init__(self):
        self.calls: list = []
        self.chat = _Chat(self)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """隔离配额/缓存库，并打桩 Gateway 客户端为可记录的假客户端。"""
    qdb = str(tmp_path / "q.db")
    cdb = str(tmp_path / "c.db")
    gate = QuotaGate(qdb, limit=3)
    llm._gateway._quota = gate
    llm._gateway._cache = _SqliteCache(cdb, 86400, 2000)
    fc = _FakeClient()
    monkeypatch.setattr(llm._gateway, "_client", lambda b, k: fc)
    return fc, gate


def _chat(content: str = "hi", **kw):
    return asyncio.run(llm.chat([{"role": "user", "content": content}], **kw))


def test_platform_quota_exhausted_raises(env):
    fc, gate = env
    llm.set_scope("u1")
    for i in range(3):
        _chat(content=f"m{i}")  # 3 次不同消息，各自计量
    with pytest.raises(llm.LLMQuotaExceeded):
        _chat(content="exhaust")  # 第 4 次超默认 3 → 配额门拦截
    assert len(fc.calls) == 3  # 3 次成功调用已发生，第 4 次未触达客户端


def test_within_quota_passes(env):
    fc, gate = env
    llm.set_scope("u1")
    assert _chat() == "fake-llm-response"
    assert len(fc.calls) == 1


def test_byok_skips_quota(env):
    fc, gate = env
    llm.set_scope("u1")
    for i in range(3):
        _chat(content=f"m{i}")  # 平台 3 次
    out = _chat(content="byok", provider={"api_key": "user-own-key", "base_url": "https://byok.example/v1", "model": "m"})
    assert out == "fake-llm-response"
    assert len(fc.calls) == 4  # BYOK 不计配额，第 4 次仍放行


def test_scope_isolation(env):
    fc, gate = env
    llm.set_scope("u1")
    for i in range(3):
        _chat(content=f"u1-{i}")  # u1 耗尽
    llm.set_scope("u2")
    assert _chat(content="u2-1") == "fake-llm-response"  # 不同 scope 独立配额


def test_cache_hit_does_not_consume_quota(env):
    fc, gate = env
    llm.set_scope("u1")
    _chat(content="same")  # 缓存未命中 → 计量 + 调用 + 写入缓存
    _chat(content="same")  # 缓存命中 → 免费返回
    assert len(fc.calls) == 1
    assert gate.used("u1") == 1  # 缓存命中不计量


def test_quota_env_unlimited(env, monkeypatch, tmp_path):
    fc, gate = env
    llm._gateway._quota = QuotaGate(str(tmp_path / "unlim.db"), limit=None)
    llm.set_scope("u1")
    for i in range(5):
        assert _chat(content=f"m{i}") == "fake-llm-response"
    assert len(fc.calls) == 5
