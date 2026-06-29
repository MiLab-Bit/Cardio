"""Search Tool — real web search via Tavily, with LLM fallback.

Architecture::

    SearchTool.search(query)
        ├── Tavily available?  →  Tavily API (real web search)
        └── else                →  LLM simulation (best-effort)

The LLM fallback ensures the system works out-of-the-box without any
external API key — useful for development and demo purposes.
"""

from __future__ import annotations

import logging
from typing import Any

from byou.config import settings
from byou.core.llm_client import get_client
from byou.tools.search.tavily_client import TavilyClient, get_tavily_client

logger = logging.getLogger(__name__)


class SearchTool:
    """Web search with Tavily backend and LLM fallback.

    Usage::

        tool = SearchTool()
        results = await tool.search("OpenAI GPT-4")
    """

    def __init__(self) -> None:
        self._tavily = get_tavily_client()
        self._use_tavily = self._tavily.is_available
        if self._use_tavily:
            logger.info("SearchTool: Tavily backend enabled")
        else:
            logger.warning(
                "SearchTool: Tavily not configured — "
                "using LLM fallback (not real web search). "
                "Set TAVILY_API_KEY in .env to enable."
            )

    async def search(
        self,
        query: str,
        max_results: int = 5,
        source: str = "web",
    ) -> list[dict[str, Any]]:
        """Search the web and return normalised results.

        Each result dict has keys:  title, url, content, score, source
        """
        logger.info("Search: %s (max=%d, source=%s)", query[:80], max_results, source)

        # ── Try Tavily first ──────────────────────────────────
        if self._use_tavily:
            results = await self._tavily.search(query, max_results=max_results)
            if results:
                return results
            # Tavily returned empty — fall through to LLM
            logger.warning("Tavily returned 0 results, falling back to LLM")

        # ── LLM fallback (no real web access) ────────────────
        return await self._llm_search(query, max_results)

    async def _llm_search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Best-effort LLM-based search simulation.

        NOTE: This does NOT access the real web.  It asks the LLM to
        recall information from its training data.  Use only as fallback.
        """
        client = get_client()
        resp = await client.chat.completions.create(
            model=settings.model_medium,
            temperature=0.3,
            messages=[{
                "role": "user",
                "content": (
                    f"Provide up to {max_results} search results for:\n\n{query}\n\n"
                    "Format each result as JSON with keys: "
                    "title, url, content (2-sentence summary), score (0-1)."
                ),
            }],
        )
        content = resp.choices[0].message.content or ""
        # Best-effort: return as a single synthetic result
        return [{
            "title": f"[LLM Simulated] {query}",
            "url": "",
            "content": content[:500],
            "score": 0.5,
            "source": "llm_fallback",
        }]

    async def search_company(self, company_name: str) -> dict[str, Any]:
        """Search for company intelligence."""
        results = await self.search(f"{company_name} 公司 规模 融资 业务 官网", 5)
        return {"company": company_name, "results": results}

    async def search_person(self, person_name: str, company: str = "") -> dict[str, Any]:
        """Search for person background."""
        q = f"{person_name} {company} 职业背景 履历 LinkedIn" if company else f"{person_name} 职业背景"
        results = await self.search(q, 5)
        return {"person": person_name, "results": results}
