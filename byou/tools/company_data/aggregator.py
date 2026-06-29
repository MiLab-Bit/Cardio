"""Multi-source company data aggregator.

Aggregates results from multiple data sources concurrently:
  - OpenCorporates (200+ jurisdictions)
  - Crunchbase (funding, valuation)
  - Tavily (web search)
  - (extendable — add more sources in _SOURCE_REGISTRY)

All sources are optional — the aggregator degrades gracefully when
API keys are missing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from byou.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
#  Normalised output schema
# ─────────────────────────────────────────────────────────────────

@dataclass
class CompanyData:
    """Normalised company data from all sources."""

    # Identity
    name: str = ""
    legal_name: str = ""
    registration_number: str = ""
    jurisdiction: str = ""          # e.g. "US-DE", "CN", "GB"

    # Business
    description: str = ""
    industry: list[str] = field(default_factory=list)
    business_model: str = ""

    # Size & financials
    employee_count: int | None = None
    employee_range: str = ""         # e.g. "51-200"
    revenue_range: str = ""
    funding_total: str = ""
    funding_stage: str = ""
    valuation: str = ""

    # Location
    headquarters: str = ""
    office_locations: list[str] = field(default_factory=list)

    # People
    founders: list[str] = field(default_factory=list)
    key_executives: list[dict[str, str]] = field(default_factory=list)

    # Web & social
    website: str = ""
    social_media: dict[str, str] = field(default_factory=dict)
    linkedin_url: str = ""

    # Risk & signals
    risk_score: float = 0.0        # 0-1, higher = riskier
    risk_flags: list[str] = field(default_factory=list)
    news_mentions: list[dict[str, str]] = field(default_factory=list)
    recent_funding: bool = False

    # Raw search results (for LLM consumption)
    raw_tavily: dict = field(default_factory=dict)   # tagged search results

    # Metadata
    data_sources: list[str] = field(default_factory=list)   # which APIs contributed
    confidence: float = 0.0         # 0-1, how complete the data is

    def merge(self, other: "CompanyData") -> "CompanyData":
        """Merge another CompanyData into this one (other wins on conflict)."""
        for field_name, _ in self.__dataclass_fields__.items():
            if field_name in ("data_sources", "confidence"):
                continue
            other_val = getattr(other, field_name)
            if other_val and not getattr(self, field_name):
                setattr(self, field_name, other_val)
            elif isinstance(other_val, list) and other_val:
                existing = getattr(self, field_name)
                setattr(self, field_name, existing + [v for v in other_val if v not in existing])
        self.data_sources = list(set(self.data_sources + other.data_sources))
        self.confidence = min(1.0, self.confidence + 0.2 * len(other.data_sources))
        return self


# ─────────────────────────────────────────────────────────────────
#  Base source adapter
# ─────────────────────────────────────────────────────────────────

class BaseCompanySource:
    """Base class for all company data sources."""

    name: str = "base"
    enabled: bool = False

    async def fetch(self, company_name: str, **kwargs) -> CompanyData | None:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────
#  OpenCorporates adapter
# ─────────────────────────────────────────────────────────────────

class OpenCorporatesSource(BaseCompanySource):
    """OpenCorporates — global company registry (200+ jurisdictions).

    API docs: https://opencorporates.com/info/api
    Free tier: 100 queries/day.
    """

    name = "opencorporates"

    def __init__(self) -> None:
        self.api_key = settings.opencorporates_api_key or ""
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning("OpenCorporates: API key not configured (OPEN_CORPORATES_API_KEY)")

    async def fetch(self, company_name: str, **kwargs) -> CompanyData | None:
        if not self.enabled:
            return None
        import httpx
        url = "https://api.opencorporates.com/v0.4/companies/search"
        params = {"q": company_name, "api_token": self.api_key, "per_page": 3}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json().get("results", {}).get("companies", [])
        except Exception as e:
            logger.warning("OpenCorporates error: %s", e)
            return None

        if not data:
            return None

        c = data[0]["company"]
        out = CompanyData()
        out.name = c.get("name", "")
        out.legal_name = c.get("registered_name", "")
        out.registration_number = c.get("company_number", "")
        out.jurisdiction = c.get("jurisdiction_code", "")
        out.website = c.get("homepage_url", "")
        out.data_sources.append(self.name)
        out.confidence = 0.3
        return out


# ─────────────────────────────────────────────────────────────────
#  Crunchbase adapter
# ─────────────────────────────────────────────────────────────────

class CrunchbaseSource(BaseCompanySource):
    """Crunchbase — startup funding & valuation data.

    API docs: https://data.crunchbase.com/docs
    """

    name = "crunchbase"

    def __init__(self) -> None:
        self.api_key = settings.crunchbase_api_key or ""
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning("Crunchbase: API key not configured (CRUNCHBASE_API_KEY)")

    async def fetch(self, company_name: str, **kwargs) -> CompanyData | None:
        if not self.enabled:
            return None
        import httpx
        headers = {"X-cb-user-key": self.api_key}
        url = f"https://api.crunchbase.com/v4/entities/organizations"
        params = {"name": company_name, "limit": 1}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    return None
                data = resp.json()
        except Exception as e:
            logger.warning("Crunchbase error: %s", e)
            return None

        # Crunchbase response parsing (simplified)
        orgs = data.get("entities", [])
        if not orgs:
            return None

        o = orgs[0].get("properties", {})
        out = CompanyData()
        out.name = o.get("name", "")
        out.description = o.get("short_description", "")
        out.founders = [f.get("value", "") for f in o.get("founders", [])]
        out.headquarters = o.get("headquarters_location_identifiers", [{}])[0].get("value", "")
        out.employee_count = o.get("num_employees", None)
        out.funding_total = o.get("total_funding_raised", "")
        out.linkedin_url = o.get("linkedin_url", "")
        out.data_sources.append(self.name)
        out.confidence = 0.4
        return out


# ─────────────────────────────────────────────────────────────────
#  Tavily web search adapter
# ─────────────────────────────────────────────────────────────────

class TavilyCompanySource(BaseCompanySource):
    """Tavily web search for company intelligence.

    Uses multi-angle search (info + news + funding + leadership)
    and heuristically extracts structured fields from results.
    """

    name = "tavily"

    def __init__(self) -> None:
        from byou.tools.search.tavily_client import get_tavily_client
        self._client = get_tavily_client()
        self.enabled = self._client.is_available
        if not self.enabled:
            logger.info("TavilyCompanySource: Tavily not configured, skipping")

    async def fetch(self, company_name: str, **kwargs) -> CompanyData | None:
        if not self.enabled:
            return None

        # Multi-angle deep search
        deep = await self._client.search_company_deep(company_name)
        if not deep or not deep.get("all_results"):
            return None

        all_results = deep["all_results"]
        out = CompanyData()
        out.raw_tavily = deep  # stash raw for LLM consumption

        # ── Heuristic field extraction ──────────────────────
        funding_results = [r for r in all_results if "funding" in r.get("_tags", [])]
        leadership_results = [r for r in all_results if "leadership" in r.get("_tags", [])]
        risk_results = [r for r in all_results if "risk" in r.get("_tags", [])]

        # Funding
        if funding_results:
            out.recent_funding = True
            # Try to extract funding amount
            for r in funding_results:
                content = r.get("content", "").lower()
                import re
                # Look for patterns like "$50M", "$1.2B", "融资 1亿"
                amounts = re.findall(r"\$[\d.]+[mb]?", content, re.I)
                if amounts:
                    out.funding_total = amounts[0]
                    break

        # Leadership → founders
        for r in leadership_results[:2]:
            content = r.get("content", "")
            # Simple heuristic: look for "CEO", "founder", "创始人" near capitalised names
            lines = content.split("\n")[:5]
            for line in lines:
                if any(kw in line for kw in ["CEO", "Founder", "创始人", "联合创始人"]):
                    # Extract potential name (capitalised words)
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p[0].isupper() and len(p) > 2:
                            name = " ".join(parts[i:i+2])
                            if name not in out.founders:
                                out.founders.append(name[:30])
                                break

        # Risk
        if risk_results:
            out.risk_score = min(1.0, out.risk_score + 0.3)
            out.risk_flags.append(f"Mentions found in {len(risk_results)} search results")

        # Website (first non-directory, non-Wikipedia result)
        for r in all_results:
            url = r.get("url", "")
            if url and not any(d in url for d in ["wikipedia", "linkedin", "crunchbase", "bing.com"]):
                out.website = url
                break

        # News mentions
        for r in all_results[:5]:
            if r.get("title"):
                out.news_mentions.append({
                    "title": r["title"],
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:200],
                })

        out.data_sources.append(self.name)
        out.confidence = 0.4  # Higher than before (0.2) thanks to multi-angle search
        return out


# ─────────────────────────────────────────────────────────────────
#  Aggregator
# ─────────────────────────────────────────────────────────────────

class CompanyDataAggregator:
    """Concurrent multi-source company data aggregator.

    Usage::

        agg = CompanyDataAggregator()
        data = await agg.fetch("OpenAI")
    """

    def __init__(self) -> None:
        from byou.config import settings as cfg

        self._sources: list[BaseCompanySource] = []  # 先初始化
        self._enabled_sources: list[BaseCompanySource] = []

        force_free = cfg.force_free_sources

        # 免费源（强制 + 条件启用）
        for cls in [TavilyCompanySource, WikipediaCompanySource, CompanyWebsiteSource]:
            src = cls()
            if src.enabled and src.name not in {s.name for s in self._sources}:
                self._sources.append(src)

        # 付费源（仅在有 key 且非强制免费模式时）
        if not force_free:
            for cls in [OpenCorporatesSource, CrunchbaseSource]:
                src = cls()
                if src.enabled and src.name not in {s.name for s in self._sources}:
                    self._sources.append(src)

        self._enabled_sources = [s for s in self._sources if s.enabled]

        if force_free:
            logger.info(
                "CompanyDataAggregator: FORCE-FREE mode — only free sources enabled (%s)",
                ", ".join(s.name for s in self._enabled_sources) or "none",
            )
        else:
            logger.info(
                "CompanyDataAggregator: %d/%d sources enabled (%s)",
                len(self._enabled_sources),
                len(self._sources),
                ", ".join(s.name for s in self._enabled_sources) or "none",
            )

    @property
    def available_sources(self) -> list[str]:
        return [s.name for s in self._enabled_sources]

    async def fetch(self, company_name: str, **kwargs) -> CompanyData:
        """Fetch and merge company data from all enabled sources concurrently."""
        logger.info("Aggregating data for: %s", company_name)

        # Run all enabled sources concurrently
        tasks = [s.fetch(company_name, **kwargs) for s in self._enabled_sources]
        results: list[CompanyData | None] = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        merged = CompanyData()
        merged.name = company_name

        for r in results:
            if isinstance(r, Exception):
                logger.warning("Source error: %s", r)
                continue
            if r is None:
                continue
            merged.merge(r)

        if not merged.data_sources:
            logger.warning("No data found for: %s (all sources returned empty)", company_name)

        logger.info(
            "Aggregated %s: sources=%s, confidence=%.1f",
            company_name,
            merged.data_sources,
            merged.confidence,
        )
        return merged

    async def fetch_batch(self, company_names: list[str]) -> dict[str, CompanyData]:
        """Fetch data for multiple companies concurrently."""
        tasks = {name: self.fetch(name) for name in company_names}
        import asyncio
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {name: r for name, r in zip(company_names, results) if not isinstance(r, Exception)}


# ─────────────────────────────────────────────────────────────────
#  Singleton
# ─────────────────────────────────────────────────────────────────

_aggregator: CompanyDataAggregator | None = None


def get_company_aggregator() -> CompanyDataAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = CompanyDataAggregator()
    return _aggregator


# ─────────────────────────────────────────────────────────────────
#  Wikipedia adapter  (100% free, no API key)
# ─────────────────────────────────────────────────────────────────

class WikipediaCompanySource(BaseCompanySource):
    """Wikipedia — free structured data for notable global companies.

    Uses wikipedia-api (MIT).  No API key, no registration, rate-limited
    only by Wikipedia's public API fair-use policy (~200 req/min).

    Covers: company description, founders, HQ, industry, website.
    Best for: well-known companies with dedicated Wikipedia articles.
    """

    name = "wikipedia"

    def __init__(self) -> None:
        self.enabled = True   # always available, no key needed
        logger.info("WikipediaCompanySource: enabled (free, no key)")

    async def fetch(self, company_name: str, **kwargs) -> CompanyData | None:
        import asyncio
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(None, self._fetch_sync, company_name)
        return out

    def _fetch_sync(self, company_name: str) -> CompanyData | None:
        try:
            import wikipediaapi
            wiki = wikipediaapi.Wikipedia(
                language="en",
                user_agent="Byou/1.0 (contact: byou-agent)",
            )
            # Try exact name, then with " (company)" suffix
            for title in (company_name, f"{company_name} (company)"):
                page = wiki.page(title)
                if page.exists():
                    return self._parse_page(page, company_name)
            return None
        except Exception as e:
            logger.warning("Wikipedia error for '%s': %s", company_name, e)
            return None

    def _parse_page(self, page, company_name: str) -> CompanyData:
        out = CompanyData()
        out.name = company_name
        out.description = (page.summary or "")[:500]

        # Parse infobox-like data from page.content or use LLM later
        # For now, extract website from page.links or summary
        text = page.text or ""

        # Try to find website in summary
        import re
        urls = re.findall(r"https?://[^\s\)\]\"'>]+", page.summary)
        if urls:
            out.website = urls[0]

        # Use page URL as reference
        out.linkedin_url = ""  # not available from Wikipedia directly
        out.data_sources.append(self.name)
        out.confidence = 0.35
        return out


# ─────────────────────────────────────────────────────────────────
#  Company website extractor  (100% free via Tavily Extract)
# ─────────────────────────────────────────────────────────────────

class CompanyWebsiteSource(BaseCompanySource):
    """Extract structured data directly from company's official website.

    Uses Tavily's /extract endpoint (included in Tavily subscription)
    to fetch full page content from the company's homepage and/or
    about/investors pages.

    Completely free if you already have Tavily (user's case ✅).
    """

    name = "website_extract"

    def __init__(self) -> None:
        from byou.tools.search.tavily_client import get_tavily_client
        self._tavily = get_tavily_client()
        self.enabled = self._tavily.is_available
        if not self.enabled:
            logger.info("CompanyWebsiteSource: Tavily not available, disabling")

    async def fetch(self, company_name: str, **kwargs) -> CompanyData | None:
        if not self.enabled:
            return None

        # Step 1: find the official website URL via a quick search
        search_results = await self._tavily.search(
            f"{company_name} official website",
            max_results=3,
            search_depth="basic",
        )
        official_url = self._find_official_url(search_results, company_name)
        if not official_url:
            return None

        # Step 2: extract full content from homepage + /about
        urls_to_extract = [official_url]
        about_url = official_url.rstrip("/") + "/about"
        urls_to_extract.append(about_url)

        extracted = await self._tavily.extract_urls(urls_to_extract)

        # Step 3: parse extracted content into CompanyData
        out = CompanyData()
        out.name = company_name
        out.website = official_url
        out = self._parse_extracted(out, extracted)
        out.data_sources.append(self.name)
        out.confidence = 0.3
        return out

    def _find_official_url(self, results: list[dict], company_name: str) -> str | None:
        """Heuristically pick the official website from search results."""
        name_lower = company_name.lower()
        for r in results:
            url = r.get("url", "")
            title = r.get("title", "").lower()
            # Skip obvious non-official domains
            if any(d in url for d in ["wikipedia", "linkedin", "crunchbase", "bing.com", "google."]):
                continue
            # Prefer result whose title/URL contains the company name
            if name_lower in title or name_lower in url.lower():
                return url
        # Fallback: first non-blacklisted result
        for r in results:
            url = r.get("url", "")
            if not any(d in url for d in ["wikipedia", "linkedin", "crunchbase"]):
                return url
        return None

    def _parse_extracted(self, out: CompanyData, extracted: list[dict]) -> CompanyData:
        """Parse Tavily extract results into structured fields."""
        full_text = " ".join(
            e.get("raw_content", e.get("content", ""))[:3000]
            for e in extracted
        ).lower()

        import re

        # Employee count
        emp_match = re.search(
            r"(\d{1,3}(?:,\d{3})*)\s*(?:employees|staff|people)",
            full_text,
            re.I,
        )
        if emp_match:
            try:
                out.employee_count = int(emp_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Founded year
        founded = re.search(r"founded\s*(?:in)?\s*(\d{4})", full_text, re.I)
        if founded:
            out.description = (out.description or "") + f" [Founded: {founded.group(1)}]"

        # Industry keywords
        industries = []
        for kw in ["saas", "fintech", "ai", "biotech", "e-commerce", "enterprise"]:
            if kw in full_text:
                industries.append(kw)
        out.industry = industries

        return out


# ─────────────────────────────────────────────────────────────────
#  Re-patch CompanyDataAggregator to include free sources
