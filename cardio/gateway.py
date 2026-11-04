"""Self-contained Cardio LLM runtime.

Previously delegated to an undeclared openclaw_core package.  All persistence
and quota accounting stays local to Cardio; this module performs no requests at
import time.  It is not a replacement for the OpenClaw system/service.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

log = logging.getLogger(__name__)


class QuotaExceeded(RuntimeError):
    """Daily platform allowance exhausted or unavailable (fail closed)."""


class QuotaGate:
    """Per-scope UTC-day atomic accounting in SQLite; BYOK bypasses this gate."""

    def __init__(self, path: str, limit: int | None = 3):
        self.path = path
        self.limit = limit

    def _connect(self) -> sqlite3.Connection:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS quota_usage ("
            "day TEXT NOT NULL, scope TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY(day, scope))"
        )
        conn.commit()
        return conn

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def used(self, scope: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT used FROM quota_usage WHERE day=? AND scope=?",
                (self._today(), scope),
            ).fetchone()
            return int(row[0]) if row else 0

    def consume(self, scope: str) -> None:
        if self.limit is None:
            return
        if self.limit < 0:
            raise QuotaExceeded("invalid daily quota configuration")
        try:
            with self._connect() as conn:
                # SQLite serializes all writers; two simultaneous calls cannot
                # both pass the final remaining unit.
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT used FROM quota_usage WHERE day=? AND scope=?",
                    (self._today(), scope),
                ).fetchone()
                used = int(row[0]) if row else 0
                if used >= self.limit:
                    raise QuotaExceeded("daily LLM quota exhausted")
                conn.execute(
                    "INSERT INTO quota_usage(day,scope,used) VALUES(?,?,1) "
                    "ON CONFLICT(day,scope) DO UPDATE SET used=used+1",
                    (self._today(), scope),
                )
        except QuotaExceeded:
            raise
        except (sqlite3.Error, OSError) as exc:
            # A missing/unwritable quota DB must not create unlimited usage.
            raise QuotaExceeded("LLM quota storage unavailable") from exc


class _SqliteCache:
    """24h bounded response cache; key creation is in Gateway and includes scope."""

    def __init__(self, path: str, ttl: float = 86400.0, capacity: int = 2000):
        self.path, self.ttl, self.capacity = path, ttl, capacity

    def _connect(self) -> sqlite3.Connection:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache ("
            "cache_key TEXT PRIMARY KEY, content TEXT NOT NULL, "
            "created_at REAL NOT NULL, hits INT NOT NULL DEFAULT 0)"
        )
        conn.commit()
        return conn

    def get(self, key: str) -> str | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT content,created_at FROM llm_cache WHERE cache_key=?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                if time.time() - float(row[1]) > self.ttl:
                    conn.execute("DELETE FROM llm_cache WHERE cache_key=?", (key,))
                    return None
                conn.execute("UPDATE llm_cache SET hits=hits+1 WHERE cache_key=?", (key,))
                return str(row[0])
        except (sqlite3.Error, OSError):
            log.warning("LLM response cache read unavailable", exc_info=True)
            return None

    def put(self, key: str, content: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO llm_cache(cache_key,content,created_at,hits) VALUES(?,?,?,1) "
                    "ON CONFLICT(cache_key) DO UPDATE SET "
                    "content=excluded.content,created_at=excluded.created_at,hits=1",
                    (key, content, time.time()),
                )
                excess = conn.execute("SELECT count(*) FROM llm_cache").fetchone()[0] - self.capacity
                if excess > 0:
                    conn.execute(
                        "DELETE FROM llm_cache WHERE cache_key IN "
                        "(SELECT cache_key FROM llm_cache ORDER BY created_at ASC LIMIT ?)",
                        (excess,),
                    )
        except (sqlite3.Error, OSError):
            log.warning("LLM response cache write unavailable", exc_info=True)


class Gateway:
    """OpenAI-compatible gateway preserving Cardio's 2026 client contract.

    Platform requests consume quota on cache miss *before* dispatch, including
    unsuccessful attempts; provider/BYOK requests are excluded.
    """

    def __init__(
        self, *, platform_base_url: str, platform_api_key: str,
        default_model: str, quota_db: str, cache_db: str,
        max_concurrency: int = 5, max_retries: int = 3,
        timeout: float = 120.0,
    ):
        self.platform_base_url = platform_base_url
        self.platform_api_key = platform_api_key
        self.default_model = default_model
        self.max_retries = max(1, max_retries)
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._quota = QuotaGate(
            quota_db, limit=int(os.getenv("CARDIO_DAILY_LLM_LIMIT", "3"))
        )
        self._cache = _SqliteCache(cache_db)

    def _client(self, base_url: str, key: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=base_url, api_key=key,
            timeout=self.timeout, max_retries=0,
        )

    @staticmethod
    def _cache_key(
        scope: str, provider: dict | None, model: str,
        temperature: float | None, max_tokens: int,
        messages: list[dict],
    ) -> str:
        if provider and provider.get("api_key"):
            # Include the *entire* hash so key rotations cannot share cached
            # private answers. Never log, persist or return the original key.
            identity = "byok:" + hashlib.sha256(
                str(provider["api_key"]).encode()
            ).hexdigest()
        else:
            identity = "platform"
        raw = json.dumps(
            [scope, identity, model, temperature, max_tokens, messages],
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    async def chat(
        self, messages: list[dict], *, model: str | None = None,
        temperature: float | None = None, max_tokens: int = 2048,
        stream: bool = False, provider: dict | None = None,
        scope: str = "anon",
    ) -> str | AsyncIterator[str]:
        byok = bool(provider and provider.get("api_key"))
        effective_model = model or (provider.get("model") if byok else None) or self.default_model
        cache_key = None
        if not stream:
            cache_key = self._cache_key(
                scope, provider, effective_model, temperature, max_tokens, messages,
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        if not byok:
            self._quota.consume(scope)
        base = (provider or {}).get("base_url") if byok else self.platform_base_url
        key = (provider or {}).get("api_key") if byok else self.platform_api_key
        client = self._client(base or self.platform_base_url, key or "sk-placeholder")

        for attempt in range(self.max_retries):
            try:
                async with self._semaphore:
                    response = await client.chat.completions.create(
                        model=effective_model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=stream,
                    )
                if stream:
                    async def tokens() -> AsyncIterator[str]:
                        async for part in response:
                            for choice in getattr(part, "choices", []) or []:
                                delta = getattr(choice, "delta", None)
                                if delta and getattr(delta, "content", None):
                                    yield delta.content
                    return tokens()

                content = response.choices[0].message.content or ""
                if cache_key is not None:
                    self._cache.put(cache_key, content)
                return content
            except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
                status = getattr(exc, "status_code", None)
                transient = status is None or status == 429 or 500 <= status < 600
                if not transient or attempt + 1 == self.max_retries:
                    raise
                await asyncio.sleep(min(2 ** attempt, 8))
        raise RuntimeError("unreachable LLM retry state")

    async def test_provider(self, provider: dict) -> dict:
        key = (provider.get("api_key") or "").strip()
        if not key:
            return {"ok": False, "error": "API Key 为空"}
        model = provider.get("model") or "gpt-4o-mini"
        base_url = provider.get("base_url")
        try:
            if (provider.get("provider") or "").lower() == "anthropic":
                import httpx
                endpoint = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.post(
                        endpoint,
                        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                        json={"model": model, "max_tokens": 4, "messages": [{"role": "user", "content": "hi"}]},
                    )
                response.raise_for_status()
            else:
                client = self._client(base_url or self.platform_base_url, key)
                await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": "hi"}],
                        max_tokens=4,
                    ),
                    timeout=25.0,
                )
            return {"ok": True, "model": model}
        except Exception as exc:
            # Never leak user BYOK credentials through an API error response.
            return {"ok": False, "error": str(exc).replace(key, "[REDACTED]")[:200]}
