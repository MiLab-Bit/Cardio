"""Enrichment Subsystem — Orchestrator.

多源 enrichment 编排引擎。

调用链路 (按 SourcePriority 排序):
  1. PRIMARY:   天眼查 → 工商基础信息 + 风险数据
  2. PRIMARY:   CRM → 已有客户记录 (只读)
  3. SECONDARY: Open Sales Stack → 技术栈 + 招聘信号
  4. FALLBACK:  Browser Research → 网页研究补充
  5. 归一化 + 去重 + 合并
  6. 输出 EnrichmentResult → ResearchBundle

成本控制:
  - max_cost 控制单次 enrichment 总点数
  - enforce_primary_source 确保至少有 1 个权威源
  - 每个 source 按需调用, 不查不需要的 capability
"""

from __future__ import annotations

import logging
import time
from typing import Any

from byou.tools.enrichment.types import (
    SourceType,
    SourcePriority,
    SourceRecord,
    EnrichmentRequest,
    EnrichmentResult,
    CompanyIdentity,
    CompanyProfile,
    CompanyRiskProfile,
    CompanyTechProfile,
    CRMAccountRef,
    ResearchBundle,
    DataProvenance,
)
from byou.tools.enrichment.policies import (
    SOURCE_PRIORITY_MAP,
    SOURCE_CAPABILITY_MAP,
    SOURCE_COST_MAP,
    FALLBACK_CHAIN,
    QuotaPolicy,
    MergePolicy,
)
from byou.tools.enrichment.identity import IdentityResolver
from byou.tools.enrichment.merger import DataMerger
from byou.tools.enrichment.adapters.tianyancha import TianYanChaAdapter
from byou.tools.enrichment.adapters.browser_bridge import BrowserBridgeAdapter
from byou.tools.enrichment.adapters.crm_adapter import CRMAdapter

logger = logging.getLogger(__name__)


class EnrichmentOrchestrator:
    """多源商务数据 enrichment 编排器。

    Usage:
        orch = EnrichmentOrchestrator(tyc_api_key="sk-xxx")
        result = await orch.enrich(EnrichmentRequest(
            company_name="阿里巴巴",
            website="https://www.alibaba.com",
            capabilities=["company_profile", "company_risk"],
        ))
        bundle = orch.to_bundle(result)
    """

    def __init__(
        self,
        tyc_api_key: str = "",
        use_browser: bool = True,
        use_crm: bool = False,
    ):
        self._resolver = IdentityResolver()
        self._merger = DataMerger()
        self._tyc = TianYanChaAdapter(api_key=tyc_api_key) if tyc_api_key else None
        self._browser = BrowserBridgeAdapter() if use_browser else None
        self._crm = CRMAdapter() if use_crm else None

    # ── 主入口 ────────────────────────────────────

    async def enrich(self, request: EnrichmentRequest) -> EnrichmentResult:
        """执行一次多源 enrichment。

        流程:
        1. 解析企业身份
        2. PRIMARY sources (天眼查, CRM)
        3. SECONDARY sources (Open Sales Stack)
        4. FALLBACK sources (Browser Research)
        5. 合并 + 去重
        6. 输出 EnrichmentResult
        """
        t_start = time.monotonic()
        result = EnrichmentResult(request=request)
        total_cost = 0

        # ── 输入验证 ──
        if not request.company_name and not request.domain:
            result.errors.append("No company_name or domain provided")
            return result

        # ── Step 1: 身份解析 ──
        identity = self._resolver.resolve(
            company_name=request.company_name,
            domain=request.domain,
        )
        result.identity = identity
        if not identity.is_resolved:
            result.errors.append(f"Identity not resolved: {request.company_name}")
            # 继续尝试，但数据质量会很低

        # ── Pick sources by capabilities ──
        sources = self._pick_sources(
            capabilities=request.capabilities,
            enforce_primary=request.enforce_primary_source,
        )
        # 按优先级排序
        sources.sort(key=lambda s: (
            0 if SOURCE_PRIORITY_MAP.get(s) == SourcePriority.PRIMARY else
            1 if SOURCE_PRIORITY_MAP.get(s) == SourcePriority.SECONDARY else 2
        ))

        # ── Step 2-4: 逐个 source 调用 ──
        for source in sources:
            # 成本控制
            next_cost = SOURCE_COST_MAP.get(source, 1)
            if total_cost + next_cost > request.max_cost:
                logger.info("Cost limit reached: %d/%d, skip %s", total_cost, request.max_cost, source)
                break

            record = await self._call_source(source, request)
            result.source_records.append(record)
            total_cost += next_cost

            if record.is_error:
                result.sources_failed += 1
                # 尝试 fallback
                if source in FALLBACK_CHAIN:
                    for fallback in FALLBACK_CHAIN[source]:
                        fb_record = await self._call_source(fallback, request)
                        result.source_records.append(fb_record)
                        if not fb_record.is_error:
                            break
            else:
                result.sources_queried += 1

        # ── 检查: 是否有 primary source ──
        if request.enforce_primary_source and not result.has_primary_source:
            result.errors.append("No primary source available")

        # ── Step 5: 合并 ──
        if result.source_records:
            merged_profile, merge_decisions = self._merger.merge_profiles(
                result.source_records,
                identity.name or request.company_name,
            )
            merged_profile.identity = identity
            result.profile = merged_profile
            result.merge_decisions = merge_decisions
            result.conflicts_detected = sum(1 for d in merge_decisions if d.conflict_detected)
            result.conflicts_resolved = result.conflicts_detected

            # 提取 Risk / Tech
            for r in result.source_records:
                if r.is_error:
                    continue
                raw = r.raw_data
                if isinstance(raw, dict):
                    if "risk" in raw and raw["risk"] is not None:
                        result.risk = raw["risk"]
                    if "tech" in raw and raw["tech"] is not None:
                        result.tech = raw["tech"]
                    if "crm_refs" in raw:
                        result.crm_refs = raw["crm_refs"]

        # ── 统计 ──
        result.total_cost = total_cost
        result.total_time_ms = round((time.monotonic() - t_start) * 1000, 1)
        result.sources_queried = result.sources_queried or sum(
            1 for r in result.source_records if not r.is_error
        )
        result.quality_score = self._compute_quality(result)

        return result

    # ── Source 调用 ────────────────────────────────

    async def _call_source(
        self, source: SourceType, request: EnrichmentRequest,
    ) -> SourceRecord:
        """调用单个数据源"""
        try:
            if source == SourceType.TIANYANCHA and self._tyc:
                data = await self._tyc.enrich(request)
                profile = data.get("profile")
                risk = data.get("risk")
                records = data.get("records", [])
                # 聚合: 第一个 record 带 profile + risk
                if records:
                    primary = records[0]
                    primary.raw_data = {
                        "profile": profile.model_dump() if profile else {},
                        "risk": risk.model_dump() if risk else None,
                    }
                primary.fetch_cost_ms = (time.monotonic() - 0) * 1000  # approximate
                primary.quota_consumed = data.get("cost", 0)
                return primary if records else SourceRecord(
                    source=source,
                    source_priority=SourcePriority.PRIMARY,
                    is_error=True,
                    error_message="No records from tianyancha",
                )

            elif source == SourceType.BROWSER_RESEARCH and self._browser:
                record = await self._browser.enrich(request)
                return record

            elif source in (SourceType.CRM_SALESFORCE, SourceType.CRM_HUBSPOT) and self._crm:
                records = await self._crm.enrich(request)
                return records[0] if records else SourceRecord(
                    source=source,
                    source_priority=SourcePriority.PRIMARY,
                    is_error=True,
                    error_message="No CRM records",
                )

            else:
                return SourceRecord(
                    source=source,
                    source_priority=SOURCE_PRIORITY_MAP.get(source, SourcePriority.FALLBACK),
                    is_error=True,
                    error_message=f"Source not configured: {source}",
                )
        except Exception as e:
            logger.exception("Source %s failed", source)
            return SourceRecord(
                source=source,
                source_priority=SOURCE_PRIORITY_MAP.get(source, SourcePriority.FALLBACK),
                is_error=True,
                error_message=str(e),
            )

    # ── Source 选择 ────────────────────────────────

    def _pick_sources(
        self, capabilities: list[str], enforce_primary: bool = True,
    ) -> list[SourceType]:
        """根据 capability 选择数据源"""
        needed = set(capabilities) if capabilities else {"company_profile"}

        sources: set[SourceType] = set()
        for src, src_caps in SOURCE_CAPABILITY_MAP.items():
            if needed & set(src_caps):
                sources.add(src)

        # 如果没有 primary source 且 enforce_primary → 加入天眼查
        if enforce_primary and not any(
            SOURCE_PRIORITY_MAP.get(s) == SourcePriority.PRIMARY for s in sources
        ):
            sources.add(SourceType.TIANYANCHA)

        return list(sources)

    # ── 质量计算 ───────────────────────────────────

    @staticmethod
    def _compute_quality(result: EnrichmentResult) -> float:
        """综合质量评分 0-1"""
        score = 0.0

        # 有 primary source
        if result.has_primary_source:
            score += 0.4

        # 身份已解析
        if result.identity.is_resolved:
            score += 0.2

        # 数据完整度 (有 industry + website + description)
        p = result.profile
        completeness = sum(1 for v in [p.industry, p.website, p.status, p.registered_capital] if v)
        score += completeness * 0.05

        # 去重后冲突少
        if result.conflicts_detected <= 2:
            score += 0.1
        else:
            score -= 0.1

        # 错误少
        if result.sources_failed == 0:
            score += 0.1

        return max(0.0, min(1.0, round(score, 2)))

    # ── ResearchBundle 构建 ────────────────────────

    def to_bundle(
        self,
        result: EnrichmentResult,
        browser_findings: list[dict[str, Any]] | None = None,
        llm_analysis: dict[str, Any] | None = None,
    ) -> ResearchBundle:
        """EnrichmentResult → ResearchBundle (供 downstream agents 消费)"""
        data_gaps: list[str] = []
        warnings: list[str] = []

        p = result.profile
        if not p.industry:
            data_gaps.append("industry")
        if not p.registered_capital:
            data_gaps.append("registered_capital")
        if not p.website:
            data_gaps.append("website")

        if not result.has_primary_source:
            warnings.append("No primary source used — data may be unreliable")
        if result.sources_failed > 0:
            warnings.append(f"{result.sources_failed} source(s) failed")

        return ResearchBundle(
            company_name=result.identity.name or result.request.company_name,
            identity=result.identity,
            profile=result.profile,
            risk=result.risk,
            tech=result.tech,
            crm_refs=result.crm_refs,
            browser_findings=browser_findings or [],
            source_records=result.source_records,
            merge_decisions=result.merge_decisions,
            quality_score=result.quality_score,
            data_quality=result.profile.data_quality,
            data_gaps=data_gaps,
            warnings=warnings,
            llm_analysis=llm_analysis or {},
            trace_id=result.request.trace_id,
        )

    async def close(self) -> None:
        if self._tyc:
            await self._tyc.close()
