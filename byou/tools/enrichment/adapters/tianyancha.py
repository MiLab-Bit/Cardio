"""Enrichment Subsystem — TianYanCha adapter.

将天眼查 REST API 包装为 enrichment source。
需要 TIANYANCHA_API_KEY 环境变量或配置。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from byou.tools.enrichment.types import (
    SourceType, SourcePriority, SourceRecord, EnrichmentRequest,
    CompanyIdentity, CompanyProfile, CompanyRiskProfile,
    DataProvenance,
)
from byou.tools.enrichment.identity import IdentityResolver
from byou.tools.enrichment.data_cleaner import normalize_tyc_response

logger = logging.getLogger(__name__)

# 天眼查 API Base
TYC_BASE = "https://open.api.tianyancha.com/services/open"

# 接口路径
TYC_ENDPOINTS = {
    "baseinfo": f"{TYC_BASE}/ic/baseinfoV3/2.0",        # 基础工商
    "equity": f"{TYC_BASE}/ic/equity/v2",                 # 股权穿透
    "courts": f"{TYC_BASE}/risk/courtNotice/v2",          # 司法风险
    "abnormal": f"{TYC_BASE}/risk/abnormalOperation/v2",   # 经营异常
    "dishonest": f"{TYC_BASE}/risk/dishonestInfo/v2",     # 失信人
    "search": f"{TYC_BASE}/search/v2/company",             # 企业搜索
}


class TianYanChaAdapter:
    """天眼查开放平台适配器。

    封装 REST API 调用 → SourceRecord → CompanyProfile + CompanyRiskProfile。

    Usage:
        adapter = TianYanChaAdapter(api_key="sk-xxx")
        profile, risk = await adapter.enrich(EnrichmentRequest(company_name="阿里巴巴"))
    """

    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._resolver = IdentityResolver()
        self._client = httpx.AsyncClient(timeout=15.0)

    # ── 主入口 ────────────────────────────────────

    async def enrich(self, request: EnrichmentRequest) -> dict[str, Any]:
        """从天眼查获取企业画像 + 风险数据。

        Returns:
            {"profile": CompanyProfile, "risk": CompanyRiskProfile,
             "records": [SourceRecord...], "cost": int}
        """
        records: list[SourceRecord] = []
        total_cost = 0

        # Step 1: 搜索企业
        company_id = ""
        search_record = await self._search_company(request.company_name)
        records.append(search_record)
        total_cost += 1
        if not search_record.is_error and search_record.raw_data:
            company_id = self._extract_company_id(search_record.raw_data)

        if not company_id:
            # 搜索无结果
            return {
                "profile": CompanyProfile(
                    identity=CompanyIdentity(name=request.company_name),
                ),
                "risk": None,
                "records": records,
                "cost": total_cost,
            }

        # Step 2: 基础工商
        basic_record = await self._get_baseinfo(request.company_name, company_id)
        records.append(basic_record)
        total_cost += 1

        # Step 3: 风险数据 (可选)
        risk_profile = None
        if request.capabilities and "company_risk" in request.capabilities:
            risk_record = await self._get_risk(request.company_name, company_id)
            records.append(risk_record)
            total_cost += 2
            risk_profile = self._build_risk_profile(risk_record)

        # Step 4: 构建 CompanyProfile
        profile = self._build_profile(basic_record, request.company_name, company_id)

        return {
            "profile": profile,
            "risk": risk_profile,
            "records": records,
            "cost": total_cost,
        }

    # ── API 调用 ───────────────────────────────────

    async def _search_company(self, name: str) -> SourceRecord:
        """企业搜索"""
        try:
            resp = await self._client.get(
                TYC_ENDPOINTS["search"],
                params={"keyword": name, "pageSize": 3},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return SourceRecord(
                source=SourceType.TIANYANCHA,
                source_priority=SourcePriority.PRIMARY,
                raw_data=data,
            )
        except Exception as e:
            logger.warning("TianYanCha search failed: %s", e)
            return SourceRecord(
                source=SourceType.TIANYANCHA,
                source_priority=SourcePriority.PRIMARY,
                is_error=True,
                error_message=str(e),
            )

    async def _get_baseinfo(self, name: str, company_id: str) -> SourceRecord:
        """基础工商信息"""
        try:
            resp = await self._client.get(
                TYC_ENDPOINTS["baseinfo"],
                params={"id": company_id},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return SourceRecord(
                source=SourceType.TIANYANCHA,
                source_priority=SourcePriority.PRIMARY,
                record_id=company_id,
                raw_data=data,
            )
        except Exception as e:
            logger.warning("TianYanCha baseinfo failed: %s", e)
            return SourceRecord(
                source=SourceType.TIANYANCHA,
                source_priority=SourcePriority.PRIMARY,
                record_id=company_id,
                is_error=True,
                error_message=str(e),
            )

    async def _get_risk(self, name: str, company_id: str) -> SourceRecord:
        """风险数据 (合并多个 endpoint)"""
        risk_data: dict[str, Any] = {"company_id": company_id}
        errors = []

        # 司法
        try:
            resp = await self._client.get(
                TYC_ENDPOINTS["courts"],
                params={"id": company_id, "pageSize": 50},
                headers=self._headers(),
            )
            resp.raise_for_status()
            risk_data["court_notices"] = resp.json()
        except Exception as e:
            errors.append(f"courts: {e}")

        # 经营异常
        try:
            resp = await self._client.get(
                TYC_ENDPOINTS["abnormal"],
                params={"id": company_id, "pageSize": 20},
                headers=self._headers(),
            )
            resp.raise_for_status()
            risk_data["abnormal"] = resp.json()
        except Exception as e:
            errors.append(f"abnormal: {e}")

        # 失信
        try:
            resp = await self._client.get(
                TYC_ENDPOINTS["dishonest"],
                params={"keyword": name, "pageSize": 20},
                headers=self._headers(),
            )
            resp.raise_for_status()
            risk_data["dishonest"] = resp.json()
        except Exception as e:
            errors.append(f"dishonest: {e}")

        return SourceRecord(
            source=SourceType.TIANYANCHA,
            source_priority=SourcePriority.PRIMARY,
            record_id=company_id,
            raw_data=risk_data,
            is_error=len(errors) >= 3,
            error_message="; ".join(errors) if errors else "",
        )

    # ── 构建 ──────────────────────────────────────

    def _build_profile(self, record: SourceRecord, company_name: str, company_id: str) -> CompanyProfile:
        """从 baseinfo API 响应构建 CompanyProfile"""
        if record.is_error or not record.raw_data:
            return CompanyProfile(
                identity=CompanyIdentity(name=company_name),
            )

        raw = record.raw_data.get("result", record.raw_data)
        if isinstance(raw, dict):
            normalized = normalize_tyc_response(raw)
        else:
            normalized = {}

        identity = self._resolver.resolve(company_name=normalized.get("name", company_name))

        # 更新 identity
        identity.unified_social_credit_code = normalized.get("unified_social_credit_code", "")
        identity.registration_number = normalized.get("registration_number", "")

        provenance = DataProvenance(
            field_name="*",
            source=SourceType.TIANYANCHA,
            source_priority=SourcePriority.PRIMARY,
            normalized_value=str(normalized.get("name", "")),
            confidence=0.95,
            source_record_id=company_id,
        )

        return CompanyProfile(
            identity=identity,
            legal_person=normalized.get("legal_person", ""),
            registered_capital=normalized.get("registered_capital", ""),
            established_date=normalized.get("established_date", ""),
            status=normalized.get("status", ""),
            address=normalized.get("address", ""),
            business_scope=normalized.get("business_scope", ""),
            website=normalized.get("website", ""),
            industry=normalized.get("industry", ""),
            provenance=[provenance],
            data_quality="high" if normalized.get("name") else "low",
        )

    def _build_risk_profile(self, record: SourceRecord) -> CompanyRiskProfile | None:
        """从风险数据构建 CompanyRiskProfile"""
        if record.is_error:
            return None

        raw = record.raw_data

        court_items = (
            raw.get("court_notices", {})
            .get("result", {})
            .get("items", [])
        )
        court_count = len(court_items) if isinstance(court_items, list) else 0

        abnormal_items = (
            raw.get("abnormal", {})
            .get("result", {})
            .get("items", [])
        )
        abnormal_count = len(abnormal_items) if isinstance(abnormal_items, list) else 0

        dishonest_items = (
            raw.get("dishonest", {})
            .get("result", {})
            .get("items", [])
        )
        dishonest_count = len(dishonest_items) if isinstance(dishonest_items, list) else 0

        # 风险评分
        risk_score = min(1.0, court_count * 0.05 + abnormal_count * 0.1 + dishonest_count * 0.2)

        if risk_score >= 0.5:
            risk_level = "critical"
        elif risk_score >= 0.3:
            risk_level = "high"
        elif risk_score >= 0.1:
            risk_level = "medium"
        else:
            risk_level = "low"

        return CompanyRiskProfile(
            company_name="",
            court_case_count=court_count,
            court_cases=court_items[:20] if isinstance(court_items, list) else [],
            is_dishonest=dishonest_count > 0,
            dishonest_count=dishonest_count,
            abnormal_operation_count=abnormal_count,
            abnormal_details=abnormal_items[:20] if isinstance(abnormal_items, list) else [],
            risk_score=round(risk_score, 2),
            risk_level=risk_level,
            risk_factors=self._identify_risk_factors(court_count, abnormal_count, dishonest_count),
            provenance=[DataProvenance(
                field_name="risk",
                source=SourceType.TIANYANCHA,
                source_priority=SourcePriority.PRIMARY,
                confidence=0.9,
                source_record_id=raw.get("company_id", ""),
            )],
        )

    @staticmethod
    def _identify_risk_factors(court: int, abnormal: int, dishonest: int) -> list[str]:
        factors = []
        if court > 10:
            factors.append(f"高频涉诉 ({court} 件)")
        elif court > 3:
            factors.append(f"有涉诉记录 ({court} 件)")
        if abnormal > 0:
            factors.append(f"经营异常 ({abnormal} 次)")
        if dishonest > 0:
            factors.append(f"失信被执行人 ({dishonest} 次)")
        return factors

    # ── 辅助 ──────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_company_id(data: dict) -> str:
        """从搜索响应中提取 company id"""
        result = data.get("result", data)
        items = result.get("items", [])
        if items and isinstance(items, list):
            return str(items[0].get("id", "") or items[0].get("companyId", ""))
        return ""

    async def close(self) -> None:
        await self._client.aclose()
