"""Enrichment Subsystem — Browser Bridge Adapter.

将浏览器研究子系统接入 Enrichment 流程。
Browser Research → SourceRecord → CompanyProfile 补充字段。
"""

from __future__ import annotations

import logging
from typing import Any

from byou.tools.enrichment.types import (
    SourceType, SourcePriority, SourceRecord, EnrichmentRequest,
    CompanyProfile, DataProvenance,
)
from byou.tools.browser.adapter import BrowserResearchAdapter
from byou.tools.browser.types import BrowserExecutionReport

logger = logging.getLogger(__name__)


class BrowserBridgeAdapter:
    """浏览器 → Enrichment 桥接适配器。

    将 BrowserResearchAdapter 的结果结构化后注入 Enrichment 流程。
    主要补充: website, company_description, products_services, contact_emails/phones。
    """

    def __init__(self):
        self._browser = BrowserResearchAdapter()

    async def enrich(
        self, request: EnrichmentRequest,
    ) -> SourceRecord:
        """浏览器研究 → SourceRecord。

        如果 request 有 website → 做官网研究
        否则 → 搜索引擎驱动 + 定向深挖
        """
        try:
            if request.website and request.website.startswith(("http://", "https://")):
                report = await self._browser.research_company_website(
                    company_name=request.company_name,
                    website_url=request.website,
                    max_depth=2,
                    headless=True,
                )
            else:
                report = await self._browser.search_and_research(
                    query=f"{request.company_name} 公司简介 产品",
                    max_results=2,
                    headless=True,
                )

            # 提取: 描述 + 产品 + 邮箱/电话
            extracted = self._extract_from_report(report)

            return SourceRecord(
                source=SourceType.BROWSER_RESEARCH,
                source_priority=SourcePriority.FALLBACK,
                raw_data=extracted,
                is_error=report.aborted,
                error_message="; ".join(report.errors[:3]) if report.aborted else "",
            )
        except Exception as e:
            logger.warning("Browser bridge enrich failed: %s", e)
            return SourceRecord(
                source=SourceType.BROWSER_RESEARCH,
                source_priority=SourcePriority.FALLBACK,
                is_error=True,
                error_message=str(e),
            )

    def _extract_from_report(self, report: BrowserExecutionReport) -> dict[str, Any]:
        """从浏览器报告提取结构化字段"""
        result: dict[str, Any] = {
            "pages_visited": len(report.pages_visited),
            "findings_count": len(report.findings),
            "errors": report.errors[:3],
        }

        # 聚合所有 finding 内容
        all_text = " ".join(f.content for f in report.findings)

        # 提取潜在邮箱
        import re
        emails = list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", all_text)))
        if emails:
            result["emails"] = emails[:5]

        # 提取潜在电话
        phones = list(set(re.findall(r"(?:\+86[-\s]?)?1[3-9]\d{9}", all_text)))
        if phones:
            result["phones"] = phones[:5]

        # 公司描述 (取第一个 finding 的前 500 字符)
        for f in report.findings:
            if f.content and len(f.content) > 50:
                result["description_candidate"] = f.content[:500]
                break

        # 提取页面标题
        result["page_titles"] = [p.title for p in report.pages_visited[:3] if p.title]

        # 网站
        if report.task.target_url:
            result["website"] = report.task.target_url

        return result
