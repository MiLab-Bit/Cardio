"""LLM 客户端封装 — 统一走 abc-ai.cn 网关，全部使用 Qwen-flash。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from typing import AsyncIterator

from openai import AsyncOpenAI

from . import config

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY or "sk-placeholder",
            timeout=120.0,
            max_retries=2,
        )
    return _client


def client_for(provider: dict | None = None) -> AsyncOpenAI:
    """按优先级选择客户端：若传入用户自带供应商配置（api_key 非空），用其 key/base_url；否则用平台网关。"""
    if provider and provider.get("api_key"):
        return AsyncOpenAI(
            base_url=provider.get("base_url") or config.LLM_BASE_URL,
            api_key=provider["api_key"],
            timeout=120.0,
            max_retries=2,
        )
    return get_client()


# ---- LLM 响应缓存（仅非流式） ----
# 复用 cardio.db 的 llm_cache 表 (cache_key PK, content, created_at REAL, hits INT)。
# 流式结果不缓存；验证调用(test_provider)走独立最小调用，不经过 chat()，天然不受影响。
# 缓存 key 含 provider id（或平台标识），避免不同用户/不同 key 的回答互相串。
_LLM_CACHE_TTL = 24 * 3600.0
_LLM_CACHE_CAP = 2000


def _cache_connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _cache_init(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache ("
        "cache_key TEXT PRIMARY KEY, content TEXT NOT NULL, "
        "created_at REAL NOT NULL, hits INT NOT NULL DEFAULT 0)"
    )
    conn.commit()


def _cache_key(
    provider: dict | None, model: str, temperature: float, messages: list[dict]
) -> str:
    if provider:
        pid = provider.get("id") or (
            "key:" + hashlib.sha256((provider.get("api_key") or "").encode()).hexdigest()[:16]
        )
    else:
        pid = "platform"
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    raw = f"{pid}|{model}|{temperature}|{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> str | None:
    """命中且未过期返回内容；过期/缺失返回 None。缓存异常不影响主流程。"""
    try:
        conn = _cache_connect()
        try:
            _cache_init(conn)
            row = conn.execute(
                "SELECT content, created_at FROM llm_cache WHERE cache_key=?", (key,)
            ).fetchone()
            if not row:
                return None
            if time.time() - row["created_at"] > _LLM_CACHE_TTL:
                conn.execute("DELETE FROM llm_cache WHERE cache_key=?", (key,))
                conn.commit()
                return None
            conn.execute("UPDATE llm_cache SET hits=hits+1 WHERE cache_key=?", (key,))
            conn.commit()
            return row["content"]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


def _cache_put(key: str, content: str) -> None:
    """写入/更新缓存，并在超出条数上限时清理最旧条目。异常不影响主流程。"""
    try:
        conn = _cache_connect()
        try:
            _cache_init(conn)
            conn.execute(
                "INSERT INTO llm_cache (cache_key, content, created_at, hits) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(cache_key) DO UPDATE SET content=excluded.content, "
                "created_at=excluded.created_at, hits=excluded.hits",
                (key, content, time.time()),
            )
            count = conn.execute("SELECT COUNT(*) AS n FROM llm_cache").fetchone()["n"]
            if count > _LLM_CACHE_CAP:
                excess = count - _LLM_CACHE_CAP
                old = conn.execute(
                    "SELECT cache_key FROM llm_cache ORDER BY created_at ASC LIMIT ?", (excess,)
                ).fetchall()
                for r in old:
                    conn.execute("DELETE FROM llm_cache WHERE cache_key=?", (r["cache_key"],))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return None


async def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    stream: bool = False,
    provider: dict | None = None,
) -> str | AsyncIterator[str]:
    """非流式返回完整文本；流式返回 token 异步迭代器。对 5xx 自动重试。

    provider：可选的用户自带大模型供应商配置 {api_key, base_url, model}，
    传入时优先用其 key 调模型，否则回退平台网关。
    """
    import asyncio

    from openai import APIStatusError, RateLimitError

    client = client_for(provider)
    effective_model = model or (provider.get("model") if provider else None) or config.LLM_MODEL
    effective_temp = temperature if temperature is not None else config.LLM_TEMPERATURE

    # 非流式：先查缓存，命中即返回（不触发供应商调用）。
    cache_key = None
    if not stream:
        cache_key = _cache_key(provider, effective_model, effective_temp, messages)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    last_err: Exception | None = None
    for attempt in range(config.LLM_MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=effective_model,
                messages=messages,
                temperature=effective_temp,
                max_tokens=max_tokens or config.LLM_MAX_TOKENS,
                stream=stream,
            )
            if stream:
                async def _gen() -> AsyncIterator[str]:
                    async for chunk in resp:
                        choices = getattr(chunk, "choices", None)
                        if not choices:
                            continue  # 跳过无 choices 的块（如仅含 usage 的末块）
                        delta = choices[0].delta
                        if delta and delta.content:
                            yield delta.content
                return _gen()
            result = resp.choices[0].message.content or ""
            if cache_key is not None:
                _cache_put(cache_key, result)
            return result
        except (APIStatusError, RateLimitError) as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            # 只对 5xx / 429 重试
            if status not in (429, 500, 502, 503, 504):
                raise
            if attempt < config.LLM_MAX_RETRIES - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err
    return ""


async def vision_chat(
    text_prompt: str,
    image_b64: str | None = None,
    *,
    model: str | None = None,
    temperature: float | None = 0.2,
    max_tokens: int | None = 1500,
    image_format: str = "jpeg",
    provider: dict | None = None,
) -> str:
    """多模态调用：支持图文输入（名片识别等）。image_b64 可为完整 data URL 或裸 base64。"""
    client = client_for(provider)
    content: list[dict] = []
    if image_b64:
        url = image_b64 if image_b64.startswith("data:") else f"data:image/{image_format};base64,{image_b64}"
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": text_prompt})
    messages = [{"role": "user", "content": content}]
    return await chat(
        messages,
        model=model or config.VISION_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        provider=provider,
    )


async def test_provider(provider: dict) -> dict:
    """验证用户自带供应商配置是否可用：用其 key 发起一次最小调用。

    支持 OpenAI 兼容网关（openai/deepseek/custom/ollama/abc-ai/google 等 base_url）。
    anthropic 走独立最小请求。返回 {ok, model?, error?}。
    """
    api_key = (provider.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "API Key 为空"}
    prov = (provider.get("provider") or "custom").lower()
    model = provider.get("model") or "gpt-4o-mini"
    base_url = provider.get("base_url")

    if prov == "anthropic":
        return await _test_anthropic(api_key, model, base_url)
    # OpenAI 兼容：用 openai SDK 发起一次最小 completion
    # 用硬超时包裹，避免无外网/网关不可达时整请求挂死（与 RedTrip/BizAtlas 一致：快速失败）。
    try:
        client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=20.0, max_retries=0)
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=4,
            ),
            timeout=25.0,
        )
        return {"ok": True, "model": resp.model if hasattr(resp, "model") else model}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "测试超时：无法在限定时间内连接供应商，请检查 base_url 或网络连通性"}
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "model" in msg.lower() and "not" in msg.lower():
            # 模型名不被接受，但 key 本身有效：换用更宽松的探测
            return {"ok": True, "model": model, "warning": "key 有效，但模型名可能不被支持：" + msg[:120]}
        return {"ok": False, "error": msg[:200]}


async def _test_anthropic(api_key: str, model: str, base_url: str | None) -> dict:
    import httpx

    url = (base_url or "https://api.anthropic.com") + "/v1/messages"
    try:
        async with httpx.AsyncClient(timeout=30.0) as hx:
            r = await hx.post(
                url,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={"model": model or "claude-3-5-sonnet-latest", "max_tokens": 4,
                      "messages": [{"role": "user", "content": "hi"}]},
            )
        if r.status_code in (200, 201):
            return {"ok": True, "model": model}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:160]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict:
    """从模型输出中尽量解析出 JSON 对象。

    先剥离常见的 ```json ... ``` 代码围栏，再尝试整体解析；
    失败再退而求其次截取首个 {...} 片段；最终失败返回 {"raw": text}。
    """
    text = (text or "").strip()
    # 去掉 ```json 围栏（模型常这样包裹输出）
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # 退路：当普通文本处理
    return {"raw": text}
