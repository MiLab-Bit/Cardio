"""Search Tool — web search powered by LLM with shared client."""

from __future__ import annotations

import logging

from byou.core.llm_client import get_client

logger = logging.getLogger(__name__)


class SearchTool:
    """Web search via LLM capabilities or external APIs."""

    async def search(self, query: str, max_results: int = 5, source: str = "web") -> list[dict]:
        logger.info("Search: %s (max=%d, source=%s)", query[:80], max_results, source)
        return await self._llm_search(query, max_results)

    async def _llm_search(self, query: str, max_results: int) -> list[dict]:
        client = get_client()
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": (
                    f"Search the web for (max {max_results} results):\n\n{query}\n\n"
                    "For each result provide: title, summary, source, confidence(0-1)."
                ),
            }],
        )
        content = resp.choices[0].message.content or ""
        return [{"title": query, "snippet": content, "source": "llm", "confidence": 0.7}]

    async def search_company(self, company_name: str) -> dict:
        results = await self.search(f"{company_name} 公司 规模 融资 业务", 5)
        return {"company": company_name, "results": results}

    async def search_person(self, person_name: str, company: str = "") -> dict:
        q = f"{person_name} {company} 职业背景 履历" if company else f"{person_name} 职业背景"
        results = await self.search(q, 5)
        return {"person": person_name, "results": results}
