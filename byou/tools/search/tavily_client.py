"""Tavily Search Client — async HTTP client with disk cache.

Cache:
  - Keyed by (query, max_results, search_depth)
  - Stored in  ~/.byou/cache/tavily/
  - TTL: 24 hours (configurable)
  - Transparent: caller doesn't need to know
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from byou.config import settings

logger = logging.getLogger(__name__)

_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_CACHE_DIR = Path.home() / ".byou" / "cache" / "tavily"
_CACHE_TTL = 86400  # 24 hours


class TavilyClient:
    """Async client for Tavily Search API with disk cache.

    Usage::

        client = TavilyClient()
        results = await client.search("OpenAI GPT-4")
    """

    def __init__(self, cache_ttl: int = _CACHE_TTL) -> None:
        self._api_key = settings.tavily_api_key
        self._enabled = bool(self._api_key)
        self._cache_ttl = cache_ttl
        if not self._enabled:
            logger.warning(
                "Tavily API key not configured (TAVILY_API_KEY). "
                "Web search will fall back to LLM simulation."
            )
        else:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            logger.info("TavilyClient: cache dir = %s", _CACHE_DIR)

    @property
    def is_available(self) -> bool:
        return self._enabled

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> list[dict[str, Any]]:
        """Execute a Tavily search (with cache)."""
        if not self._enabled:
            return []

        # Check cache
        cache_key = self._cache_key(query, max_results, search_depth, include_answer)
        cached = self._cache_read(cache_key)
        if cached is not None:
            logger.info("Tavily cache HIT: '%s'", query[:60])
            return cached

        # Call API
        results = await self._call_api(query, max_results, search_depth, include_answer)
        if results:
            self._cache_write(cache_key, results)

        return results

    async def search_multi(self, queries: list[str], max_results: int = 3) -> list[dict[str, Any]]:
        """Concurrent search for multiple queries.  Returns merged, deduped results."""
        import asyncio
        tasks = [self.search(q, max_results=max_results) for q in queries]
        all_results: list[list[dict]] = await asyncio.gather(*tasks)
        return self._dedup([r for sub in all_results for r in sub])

    async def search_company_deep(self, company_name: str) -> dict[str, Any]:
        """Multi-angle company search: info + news + funding + risks.

        Returns dict with keys: info, news, funding, risks, all_results
        """
        queries = [
            f"{company_name} company profile size revenue employees",
            f"{company_name} latest news 2025 funding valuation",
            f"{company_name} competitors market position analysis",
            f"{company_name} CEO founder leadership team",
        ]
        all_results = await self.search_multi(queries, max_results=3)

        # Simple heuristic tagging
        for r in all_results:
            content = (r.get("title", "") + " " + r.get("content", "")).lower()
            tags: list[str] = []
            if any(w in content for w in ["funding", "raised", "valuation", "融资", "估值"]):
                tags.append("funding")
            if any(w in content for w in ["ceo", "founder", "leadership", "创始人", "ceo"]):
                tags.append("leadership")
            if any(w in content for w in ["competitor", "market", "竞争对手", "市场"]):
                tags.append("market")
            if any(w in content for w in ["risk", "lawsuit", "court", "风险", "诉讼"]):
                tags.append("risk")
            r["_tags"] = tags

        return {
            "company": company_name,
            "total_results": len(all_results),
            "all_results": all_results,
        }

    # ── Internal ────────────────────────────────────────────────

    async def _call_api(
        self,
        query: str,
        max_results: int,
        search_depth: str,
        include_answer: bool,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": include_answer,
            "include_raw_content": False,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(_TAVILY_ENDPOINT, json=payload)
                resp.raise_for_status()
                data: dict = resp.json()
        except httpx.TimeoutException:
            logger.error("Tavily search timed out for query: %s", query[:60])
            return []
        except httpx.HTTPStatusError as e:
            logger.error(
                "Tavily API error %d: %s",
                e.response.status_code,
                e.response.text[:200],
            )
            return []
        except Exception as e:
            logger.error("Tavily search failed: %s", e)
            return []

        results: list[dict[str, Any]] = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
                "source": "tavily",
            })

        answer = data.get("answer", "")
        if answer and include_answer:
            results.insert(0, {
                "title": f"AI Summary: {query}",
                "url": "",
                "content": answer,
                "score": 1.0,
                "source": "tavily_answer",
            })

        logger.info("Tavily: '%s' → %d results", query[:60], len(results))
        return results

    # ── Cache ───────────────────────────────────────────────────

    @staticmethod
    def _cache_key(query: str, max_results: int, search_depth: str, include_answer: bool) -> str:
        raw = f"{query}|{max_results}|{search_depth}|{include_answer}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, key: str) -> Path:
        return _CACHE_DIR / f"{key}.json"

    def _cache_read(self, key: str) -> list[dict] | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("_cached_at", 0) > self._cache_ttl:
                path.unlink(missing_ok=True)
                return None
            return data["results"]
        except Exception:
            return None

    def _cache_write(self, key: str, results: list[dict]) -> None:
        try:
            self._cache_path(key).write_text(
                json.dumps({"_cached_at": time.time(), "results": results}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Tavily cache write failed: %s", e)

    @staticmethod
    def _dedup(results: list[dict]) -> list[dict]:
        """Deduplicate by URL, keep highest-score version."""
        seen: dict[str, dict] = {}
        for r in results:
            url = r.get("url", "")
            if not url:
                # No URL = answer/snippet, keep all
                seen[f"__no_url_{id(r)}"] = r
                continue
            if url not in seen or r.get("score", 0) > seen[url].get("score", 0):
                seen[url] = r
        return list(seen.values())


# ── Module-level singleton ───────────────────────────────────────
_tavily_client: TavilyClient | None = None


def get_tavily_client() -> TavilyClient:
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = TavilyClient()
    return _tavily_client
