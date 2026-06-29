"""Researcher Agent — company / person background investigation.

使用 ToolBus 声明式调用外部工具: 按 capability 声明依赖, 不写死工具名。
数据源: TianYanCha API → ToolBus → LLM enrichment → CompanyIntelligence

MCP Tool Bus 改造重点:
- 不再直接实例化 TianYanChaTool
- 通过 self.call_tool(capability, arguments) 调用
- capability 在 registry 启动时注册，Agent 侧只声明需求
"""

from __future__ import annotations

import json
import logging
from typing import Any

from byou.agents.base import BaseAgent
from byou.models.company_intelligence import (
    CompanyIntelligence,
    CompanyInfo,
    CourtCase,
    EquityHolding,
)
from byou.tools.company_data import get_company_aggregator  # 全球多源数据聚合

logger = logging.getLogger(__name__)


class ResearcherAgent(BaseAgent):
    """深度企业/人物调研 Agent。

    四步流程:
    1. ToolBus → 企业 API 拉结构化数据 (COMPANY_LOOKUP + RISK_ASSESSMENT)
    2. Browser → 网页研究补充 (BROWSER_AUTOMATE) [Browser 研究]
    3. LLM enrichment → 综合推理
    4. Merge → CompanyIntelligence (强类型输出)
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="researcher",
            description="Deep background research on companies/people/industries",
            temperature=0.5,
            **kwargs,
        )
        self._browser_adapter = None  # lazy init

    def _default_prompt(self) -> str:
        return """You are a business research analyst.

Research the given company and person, output valid JSON:
{
  "company_info": {
    "full_name": "", "founded": "", "headquarters": "",
    "employee_count": "", "revenue_range": "", "funding_stage": "",
    "key_products": [], "website": "", "social_media": {}
  },
  "industry_analysis": "",
  "person_background": {
    "education": "", "career_history": [], "expertise": [], "social_presence": ""
  },
  "news_mentions": [],
  "competitors": [],
  "market_position": "",
  "relevance_score": 0.0,
  "risk_score": 0.0,
  "risk_reasons": []
}
Mark uncertain info explicitly. relevance_score 0-1 for BD fit.
risk_score 0-1: higher = riskier (court cases, abnormal operations, etc.)."""

    async def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        company: str = input_data.get("company_name", "")
        person: str = input_data.get("person_name", "")
        profile: dict = input_data.get("profile", {})

        # ── Step 0: 全球多源数据聚合（新增）────────────────
        # 并发查询 OpenCorporates / Crunchbase / Tavily
        # 作为补充数据源，不影响原有天眼查路径
        global_data = None
        try:
            aggregator = get_company_aggregator()
            if aggregator.available_sources:
                global_data = await aggregator.fetch(company)
                logger.info(
                    "Global data aggregated: sources=%s confidence=%.2f",
                    global_data.data_sources,
                    global_data.confidence,
                )
        except Exception as e:
            logger.warning("Global data aggregation failed: %s", e)

        # ── Step 1a: 尝试 EnrichmentOrchestrator (优先) ──
        enrichment_result = None
        try:
            enrichment_result = await self._enrich_via_l4(company, profile)
        except Exception as e:
            logger.warning("Enrichment failed: %s", e)

        # ── Step 1b: 企业 API 数据 (MCP Tool Bus fallback) ──
        tyc_data: dict[str, Any] = {}
        if company and self.has_tools and not enrichment_result:
            tyc_data = await self._fetch_company_data(company)

        # ── Step 2: 浏览器网页研究 [Browser 研究] ────────────
        browser_data: dict[str, Any] = {}
        if company and not enrichment_result:
            try:
                browser_data = await self._fetch_web_data(
                    company=company,
                    website=profile.get("website", ""),
                )
            except Exception as e:
                logger.warning("Browser research failed: %s", e)
                browser_data = {"error": str(e)}

        # ── 如果 Enrichment 成功, 用其标准化结果 ──────────
        if enrichment_result and enrichment_result.sources_queried > 0:
            result = self._l4_result_to_output(enrichment_result, company)
            result = await self._attach_html_report(result, company)
            return result

        # ── Step 3: LLM enrichment (MCP Bus + Browser 传统路径) ──
        queries = self._build_queries(company, person, profile)
        tyc_summary = self._summarize_tyc(tyc_data) if tyc_data else ""
        browser_summary = self._summarize_browser(browser_data) if browser_data else ""

        try:
            prompt_parts = [
                "Research this target:",
                f"Company: {company or 'unknown'}",
                f"Person: {person or 'unknown'}",
                f"Known info: {json.dumps(profile, ensure_ascii=False)}",
            ]
            if tyc_summary:
                prompt_parts.append(
                    f"\nStructured data from enterprise API (China focus):\n{tyc_summary}\n"
                    "Use this as authoritative source for company_info fields."
                )
            if global_data and global_data.data_sources:
                # 把全球聚合数据格式化为 LLM 友好的文本
                g_parts = ["\nGlobal company data (multi-source):"]
                gd = global_data
                if gd.legal_name:
                    g_parts.append(f"  Legal name: {gd.legal_name}")
                if gd.jurisdiction:
                    g_parts.append(f"  Jurisdiction: {gd.jurisdiction}")
                if gd.description:
                    g_parts.append(f"  Description: {gd.description}")
                if gd.industry:
                    g_parts.append(f"  Industry: {', '.join(gd.industry)}")
                if gd.employee_count or gd.employee_range:
                    g_parts.append(f"  Employees: {gd.employee_count or gd.employee_range}")
                if gd.funding_total:
                    g_parts.append(f"  Funding: {gd.funding_total}")
                if gd.valuation:
                    g_parts.append(f"  Valuation: {gd.valuation}")
                if gd.headquarters:
                    g_parts.append(f"  HQ: {gd.headquarters}")
                if gd.website:
                    g_parts.append(f"  Website: {gd.website}")
                if gd.linkedin_url:
                    g_parts.append(f"  LinkedIn: {gd.linkedin_url}")
                if gd.founders:
                    g_parts.append(f"  Founders: {', '.join(gd.founders)}")
                g_parts.append(f"  Data sources: {', '.join(gd.data_sources)}")
                g_parts.append(f"  Confidence: {gd.confidence:.0%}")
                prompt_parts.append("\n".join(g_parts))

            # ── Raw Tavily tagged results (multi-angle search) ──────────
            if global_data and global_data.raw_tavily:
                rt = global_data.raw_tavily
                all_results = rt.get("all_results", [])
                if all_results:
                    tagged = {}
                    for r in all_results:
                        for tag in r.get("_tags", []):
                            tagged.setdefault(tag, []).append(r)
                    tv_parts = ["\nMulti-angle web search results:"]
                    for tag, items in tagged.items():
                        tv_parts.append(f"\n  [{tag.upper()}]")
                        for r in items[:2]:
                            content = r.get("content", "")[:300]
                            tv_parts.append(f"    - {content}")
                    prompt_parts.append("\n".join(tv_parts))

            if browser_summary:
                prompt_parts.append(
                    f"\nWeb research findings:\n{browser_summary}\n"
                    "Use this to supplement industry_analysis, news_mentions, and competitors."
                )
            prompt_parts.append("\nKey questions:\n" + "\n".join(f"- {q}" for q in queries))

            llm_result = await self.call_llm_json([
                {"role": "user", "content": "\n".join(prompt_parts)},
            ])

            # ── Step 3: Merge into CompanyIntelligence ──
            intelligence = self._merge(tyc_data, llm_result, company, global_data)
            result = intelligence.model_dump()
            result["_queries"] = queries

            # ── Auto-generate HTML report ─────────────────────
            result = await self._attach_html_report(result, company)

            return result

        except Exception:
            logger.exception("Researcher failed")
            error_result = {
                "company_name": company,
                "company_info": {},
                "source": "error",
                "industry_analysis": "",
                "person_background": {},
                "news_mentions": [],
                "competitors": [],
                "market_position": "unknown",
                "risk_score": 0.0,
            }
            error_result = await self._attach_html_report(error_result, company)
            return error_result

    # ── Enrichment 路径 ────────────────────────────

    async def _enrich_via_l4(
        self, company: str, profile: dict
    ) -> "EnrichmentResult | None":
        """尝试通过 EnrichmentOrchestrator 获取企业画像。

        如果配置了天眼查 API Key, 走完整的 multi-source enrichment:
          PRIMARY → 天眼查 (工商+风险)
          FALLBACK → 浏览器研究
        """
        try:
            from byou.tools.enrichment import EnrichmentOrchestrator, EnrichmentRequest

            # 从环境变量取 key (也可从 config)
            import os
            tyc_key = os.environ.get("TIANYANCHA_API_KEY", "")

            if not tyc_key:
                logger.debug("No TIANYANCHA_API_KEY set, skip enrichment")
                return None

            orch = EnrichmentOrchestrator(
                tyc_api_key=tyc_key,
                use_browser=True,
                use_crm=False,  # CRM 待后续对接
            )

            request = EnrichmentRequest(
                company_name=company,
                website=profile.get("website", ""),
                capabilities=["company_profile", "company_risk"],
                enforce_primary_source=True,
                max_cost=20,
            )

            result = await orch.enrich(request)
            await orch.close()
            return result

        except ImportError:
            logger.debug("Enrichment module not available")
            return None
        except Exception as e:
            logger.warning("Enrichment orchestration failed: %s", e)
            return None

    @staticmethod
    def _l4_result_to_output(result: "EnrichmentResult", company: str) -> dict[str, Any]:
        """EnrichmentResult → ResearcherAgent 输出格式"""
        p = result.profile
        r = result.risk
        i = result.identity

        company_info = {
            "full_name": i.name or company,
            "legal_person": p.legal_person,
            "registered_capital": p.registered_capital,
            "established_date": p.established_date,
            "status": p.status,
            "address": p.address,
            "business_scope": p.business_scope[:300] if p.business_scope else "",
            "website": p.website,
            "industry": p.industry,
        }

        risk_score = r.risk_score if r else 0.0
        risk_reasons = r.risk_factors if r else []

        return {
            "company_name": company,
            "company_info": company_info,
            "source": "enrichment_l4",
            "industry_analysis": f"行业: {p.industry or '未识别'}",
            "person_background": {},
            "news_mentions": [],
            "competitors": [],
            "market_position": "",
            "risk_score": risk_score,
            "risk_reasons": risk_reasons,
            "data_quality": result.data_quality,
            "_enrichment_quality": result.quality_score,
            "_conflicts": result.conflicts_detected,
            "_sources": result.sources_queried,
        }

    # ── ToolBus: 获取企业数据 ────────────────────────────

    async def _fetch_company_data(self, company: str) -> dict[str, Any]:
        """通过 ToolBus 按 capability 获取企业数据。

        不写死工具名 (不直接调 TianYanChaTool)，而是声明能力标签。
        ToolBus 负责:
        1. 从 Registry 找到最佳工具 (天眼查优先, 企查查 fallback)
        2. 注入鉴权 token
        3. 执行调用 (带超时/重试/熔断)
        4. 拼合多个能力的结果
        """
        from byou.tools.mcp import ToolCapability

        tyc_data: dict[str, Any] = {}

        # 工商基础信息
        try:
            result = await self.call_tool(
                capability=ToolCapability.COMPANY_LOOKUP,
                arguments={"company_name": company},
            )
            if result and result.data:
                tyc_data["basic"] = result.data
        except Exception as e:
            logger.warning("COMPANY_LOOKUP failed: %s", e)
            tyc_data["basic"] = {"error": str(e)}

        # 股权穿透 (可选, 有 company_id 才调)
        if "basic" in tyc_data and "id" in tyc_data.get("basic", {}):
            try:
                result = await self.call_tool(
                    capability=ToolCapability.EQUITY_ANALYSIS,
                    arguments={"company_id": tyc_data["basic"]["id"]},
                )
                if result and result.data:
                    tyc_data["equity"] = result.data
            except Exception as e:
                logger.warning("EQUITY_ANALYSIS failed: %s", e)

        # 风险调查
        try:
            result = await self.call_tool(
                capability=ToolCapability.RISK_ASSESSMENT,
                arguments={"company_name": company},
            )
            if result and result.data:
                tyc_data["court_notices"] = result.data.get("court_notices", {})
                tyc_data["abnormal"] = result.data.get("abnormal", {})
        except Exception as e:
            logger.warning("RISK_ASSESSMENT failed: %s", e)

        return tyc_data

    # ── Merge helpers ─────────────────────────────────────────

    def _merge(
        self,
        tyc_data: dict,
        llm_result: dict,
        company_name: str,
        global_data: "CompanyData | None" = None,
    ) -> CompanyIntelligence:
        """Merge 企业 API 结构化数据 + LLM enrichment + 全球聚合数据 → CompanyIntelligence。"""

        from byou.tools.data_cleaner import normalize_tyc_response

        # Start from API structured data
        tyc_basic = tyc_data.get("basic", {})
        if tyc_basic and "error" not in tyc_basic:
            normalized = normalize_tyc_response(tyc_basic)
            comp_info = CompanyInfo(**{
                k: v for k, v in normalized.items() if k in CompanyInfo.model_fields
            })
            source = "tianyancha"
        else:
            ci = llm_result.get("company_info", {})
            comp_info = CompanyInfo(
                name=company_name,
                reg_number=ci.get("reg_number", ""),
                status="unknown",
            )
            source = "llm"

        # ── Overlay global aggregated data (if available) ──────────
        if global_data and global_data.data_sources:
            gd = global_data
            # Only override empty fields with aggregated data
            if not comp_info.name or comp_info.name == company_name:
                comp_info.name = gd.name or gd.legal_name or comp_info.name
            if not comp_info.website:
                comp_info.website = gd.website
            # Store global data in source field for downstream use
            source = f"{source}+global({','.join(gd.data_sources)})"

        # Equity holders
        equity_raw = tyc_data.get("equity", {})
        holders: list[EquityHolding] = []
        if isinstance(equity_raw, dict) and "items" in equity_raw:
            for item in equity_raw["items"][:10]:
                holders.append(EquityHolding(
                    holder_name=str(item.get("name", "") or item.get("holderName", "")),
                    holding_ratio=float(item.get("ratio", 0) or item.get("holdingRatio", 0)),
                    is_controller=bool(
                        item.get("isController") or item.get("controller", False)
                    ),
                ))

        # Court cases
        court_raw = tyc_data.get("court_notices", {})
        cases: list[CourtCase] = []
        if isinstance(court_raw, dict) and "items" in court_raw:
            for item in court_raw["items"][:20]:
                cases.append(CourtCase(
                    case_no=str(item.get("caseNo", "")),
                    case_type=str(item.get("caseType", "")),
                    plaintiff=str(item.get("plaintiff", "")),
                    defendant=str(item.get("defendant", "")),
                    amount_yuan=float(item.get("amount", 0) or 0),
                    judgment_date=item.get("judgmentDate"),
                    result=str(item.get("result", "")),
                ))

        # Risk score: API data + LLM assessment + global signals
        llm_risk = float(llm_result.get("risk_score", 0))
        tyc_risk = min(1.0, len(cases) * 0.1 + (1 if tyc_data.get("abnormal", {}).get("items") else 0) * 0.3)
        global_risk = global_data.risk_score if global_data else 0.0
        risk_score = max(llm_risk, tyc_risk, global_risk)

        abnormal_count = (
            len(tyc_data.get("abnormal", {}).get("items", []))
            if isinstance(tyc_data.get("abnormal"), dict)
            else 0
        )

        # News: merge from global data too
        news = llm_result.get("news_mentions", [])
        if global_data and global_data.news_mentions:
            existing = {n.get("title", "") for n in news}
            for nm in global_data.news_mentions:
                if nm.get("title", "") not in existing:
                    news.append(nm)

        return CompanyIntelligence(
            company_info=comp_info,
            company_name=company_name,
            source=source,
            equity_holders=holders,
            court_cases=cases,
            abnormal_count=abnormal_count,
            industry_analysis=llm_result.get("industry_analysis", ""),
            person_background=llm_result.get("person_background", {}),
            news_mentions=news,
            competitors=llm_result.get("competitors", []),
            market_position=llm_result.get("market_position", ""),
            risk_score=round(risk_score, 2),
            data_quality="high" if source != "llm" else "medium",
        )

    @staticmethod
    def _summarize_tyc(tyc_data: dict) -> str:
        if not tyc_data or "error" in tyc_data:
            return ""
        basic = tyc_data.get("basic", {})
        if not basic:
            return ""
        return json.dumps({
            "name": basic.get("name") or basic.get("companyName", ""),
            "legal_person": basic.get("legalPersonName", ""),
            "reg_capital": basic.get("regCapital", ""),
            "established": basic.get("estiblishTime") or basic.get("fromTime", ""),
            "status": basic.get("registStatus", ""),
            "address": basic.get("address") or basic.get("regLocation", ""),
            "scope": str(basic.get("businessScope", ""))[:200],
            "equity_holders": len(tyc_data.get("equity", {}).get("items", [])),
            "court_notices": len(tyc_data.get("court_notices", {}).get("items", [])),
        }, ensure_ascii=False)

    def _build_queries(self, company: str, person: str, profile: dict) -> list[str]:
        q: list[str] = []
        if company:
            q += [
                f"{company} — scale, funding, business model",
                f"{company} — market position & competitors",
                f"{company} — recent news / developments",
            ]
        if person:
            q += [
                f"{person} — career & expertise",
                f"{person} — industry influence",
            ]
        return q or ["Infer profile from available info"]

    # ── Browser: 网页研究数据 [Browser 研究] ─────────────────

    async def _fetch_web_data(
        self, company: str, website: str = ""
    ) -> dict[str, Any]:
        """通过浏览器子系统获取网页研究数据。

        - 如果有官网 URL → 公司官网研究
        - 否则 → 搜索引擎驱动 + 指定站点定向
        - 调用 BrowserResearchAdapter，返回 BrowserExecutionReport
        """
        from byou.tools.browser.adapter import BrowserResearchAdapter

        if not self._browser_adapter:
            self._browser_adapter = BrowserResearchAdapter()

        adapter = self._browser_adapter

        # 模式 1: 有官网 → 官网研究
        if website and website.startswith(("http://", "https://")):
            report = await adapter.research_company_website(
                company_name=company,
                website_url=website,
                max_depth=2,
                headless=True,
            )
            return self._browser_report_to_dict(report)

        # 模式 2: 搜索引擎驱动
        search_report = await adapter.search_and_research(
            query=f"{company} 公司简介 业务 产品",
            max_results=3,
            headless=True,
        )

        # 模式 3: 如果有从搜索引擎找到的链接，做定向研究
        result = {"search": self._browser_report_to_dict(search_report)}

        # 从搜索结果中提取前 2 个外部链接做定向研究
        urls = []
        for page in search_report.extracted_data[:2]:
            for link in page.key_links[:3]:
                href = link.get("href", "")
                if href and href.startswith("http") and "bing.com" not in href:
                    urls.append(href)
            if len(urls) >= 2:
                break

        if urls:
            target_report = await adapter.targeted_research(
                urls=urls,
                description=f"定向研究 {company} 相关页面",
                headless=True,
            )
            result["targeted"] = self._browser_report_to_dict(target_report)

        return result

    @staticmethod
    def _browser_report_to_dict(report) -> dict[str, Any]:
        """BrowserExecutionReport → dict 摘要"""
        from byou.tools.browser.types import BrowserExecutionReport
        if not isinstance(report, BrowserExecutionReport):
            return {}
        return {
            "task": report.task.description,
            "pages_visited": len(report.pages_visited),
            "steps": f"{report.success_steps}/{report.total_steps}",
            "findings_count": len(report.findings),
            "errors": report.errors[:5],
            "extracted_summary": [
                {
                    "url": ed.url,
                    "title": ed.title,
                    "paragraphs": ed.key_paragraphs[:3],
                }
                for ed in report.extracted_data[:3]
            ],
            "findings": [
                {
                    "source": f.source_url,
                    "title": f.source_title,
                    "content": f.content[:300],
                    "confidence": f.confidence,
                }
                for f in report.findings[:5]
            ],
        }

    @staticmethod
    def _summarize_browser(browser_data: dict) -> str:
        """将浏览器研究结果压缩为 LLM 友好的摘要"""
        if not browser_data or "error" in browser_data:
            return ""

        pieces = []
        for mode_key in ("search", "targeted"):
            mode_data = browser_data.get(mode_key, {})
            if not mode_data:
                continue

            for ed in mode_data.get("extracted_summary", []):
                pieces.append(
                    f"## {ed.get('title', 'Untitled')}\n"
                    f"URL: {ed.get('url', '')}\n" +
                    "\n".join(ed.get("paragraphs", [])[:3])
                )

            for f in mode_data.get("findings", []):
                content = f.get("content", "")
                if content and content not in "\n".join(pieces):
                    pieces.append(f"Source: {f.get('source', '')}\n{content[:300]}")

        return "\n\n".join(pieces[:8])

    # ── HTML Report (黑客松演示) ──────────────────────────────

    async def _attach_html_report(self, result: dict[str, Any], company: str) -> dict[str, Any]:
        """生成 HTML 背调报告，保存到 output_dir，并把路径注入 result。

        - 如果 settings.output_dir 不存在，自动创建
        - 生成的文件名: {company_name}_report_{timestamp}.html
        - 把 html_report_path 注入 result，供下游使用
        """
        try:
            from byou.tools.report_generator import generate_html_report_from_dict
            from byou.config import settings as cfg
            import time

            output_dir = cfg.settings.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = int(time.time())
            safe_name = "".join(
                c for c in company if c.isalnum() or c in (" ", "-", "_")
            ).rstrip() or "unknown"
            filename = f"{safe_name}_report_{timestamp}.html"
            output_path = output_dir / filename

            html_content = generate_html_report_from_dict(result)
            output_path.write_text(html_content, encoding="utf-8")

            result["html_report_path"] = str(output_path)
            result["report_url"] = f"/reports/{filename}"  # for API serving
            logger.info("HTML report saved: %s", output_path)
        except Exception as e:
            logger.warning("HTML report generation failed: %s", e)
            result["html_report_path"] = ""
            result["report_url"] = ""

        return result
