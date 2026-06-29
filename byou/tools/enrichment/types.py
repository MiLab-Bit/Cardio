"""Enrichment Subsystem — 强类型数据模型。

定义了 Byou 商务数据接入层的所有核心数据结构。
支持多源 enrichment、provenance 追溯、合并去重、source ranking。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════
# Source / Provenance
# ═══════════════════════════════════════════════════════════════════

class SourceType(str, Enum):
    """数据源类型"""
    TIANYANCHA = "tianyancha"
    CRM_SALESFORCE = "crm_salesforce"
    CRM_HUBSPOT = "crm_hubspot"
    OPEN_SALES_STACK = "open_sales_stack"
    BROWSER_RESEARCH = "browser_research"  # Browser
    EXTRACTED_CARD = "extracted_card"      # OCR
    AGENT_INFERRED = "agent_inferred"      # LLM 推理


class SourcePriority(str, Enum):
    """数据源优先级"""
    PRIMARY = "primary"      # 最权威 (工商/CRM)
    SECONDARY = "secondary"  # 辅助 (技术栈/招聘)
    FALLBACK = "fallback"    # 兜底 (搜索/推理)
    UNVERIFIED = "unverified"


class DataProvenance(BaseModel):
    """单字段的来源追溯"""
    field_name: str
    source: SourceType
    source_priority: SourcePriority
    raw_value: str = ""
    normalized_value: str = ""
    confidence: float = 1.0  # 0-1
    fetched_at: datetime = Field(default_factory=datetime.now)
    source_record_id: str = ""  # e.g. 天眼查 company id
    is_overridden: bool = False
    override_reason: str = ""


class SourceRecord(BaseModel):
    """单个数据源的原始记录"""
    source: SourceType
    source_priority: SourcePriority
    record_id: str = ""
    raw_data: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=datetime.now)
    fetch_cost_ms: float = 0
    quota_consumed: int = 0               # 消耗的 API 点数
    is_error: bool = False
    error_message: str = ""
    is_cached: bool = False


# ═══════════════════════════════════════════════════════════════════
# Company Identity
# ═══════════════════════════════════════════════════════════════════

class CompanyIdentity(BaseModel):
    """企业身份 — 用于去重和跨源关联"""
    # 主键候选
    name: str = ""                        # 标准全称
    unified_social_credit_code: str = ""  # 统一社会信用代码
    registration_number: str = ""

    # 别名与匹配
    aliases: list[str] = Field(default_factory=list)     # 曾用名
    short_names: list[str] = Field(default_factory=list) # 简称
    domains: list[str] = Field(default_factory=list)     # 官网域名
    alternative_names: list[str] = Field(default_factory=list)

    # 匹配元数据
    resolved_by: SourceType | None = None
    resolution_confidence: float = 0.0    # 多候选时的置信度
    is_fuzzy_match: bool = False
    fuzzy_match_score: float = 0.0

    # 多候选
    candidates: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return bool(self.name and self.resolution_confidence >= 0.7)


class CompanyProfile(BaseModel):
    """归一化后的企业画像 — ResearcherAgent 的主输出"""
    identity: CompanyIdentity = Field(default_factory=CompanyIdentity)

    # 基础工商
    legal_person: str = ""
    registered_capital: str = ""
    established_date: str = ""
    status: str = ""                      # 存续/注销/吊销
    address: str = ""
    business_scope: str = ""

    # 规模
    employee_count: str = ""
    employee_count_range: str = ""
    revenue_range: str = ""
    market_cap: str = ""

    # 行业
    industry: str = ""
    industry_tags: list[str] = Field(default_factory=list)
    business_model: str = ""

    # 联系
    website: str = ""
    contact_emails: list[str] = Field(default_factory=list)
    contact_phones: list[str] = Field(default_factory=list)

    # 社交媒体
    social_links: dict[str, str] = Field(default_factory=dict)

    # 描述
    company_description: str = ""
    products_services: list[str] = Field(default_factory=list)
    key_customers: list[str] = Field(default_factory=list)

    # 来源
    provenance: list[DataProvenance] = Field(default_factory=list)
    enrichment_timestamp: datetime = Field(default_factory=datetime.now)
    data_quality: str = "low"             # low / medium / high


class CompanyRiskProfile(BaseModel):
    """企业风险画像"""
    company_name: str = ""

    # 司法
    court_case_count: int = 0
    court_cases: list[dict[str, Any]] = Field(default_factory=list)
    is_dishonest: bool = False            # 失信被执行人
    dishonest_count: int = 0

    # 经营异常
    abnormal_operation_count: int = 0
    abnormal_details: list[dict[str, Any]] = Field(default_factory=list)

    # 行政处罚
    admin_penalty_count: int = 0
    admin_penalties: list[dict[str, Any]] = Field(default_factory=list)

    # 综合评分
    risk_score: float = 0.0               # 0=无风险, 1=高风险
    risk_level: str = "low"               # low / medium / high / critical
    risk_factors: list[str] = Field(default_factory=list)

    provenance: list[DataProvenance] = Field(default_factory=list)


class CompanyTechProfile(BaseModel):
    """企业技术栈画像（来自 Open Sales Stack / BuiltWith 等）"""
    company_name: str = ""

    # 技术栈
    detected_tech: list[str] = Field(default_factory=list)  # ["React", "AWS", "Python"]
    hosting_providers: list[str] = Field(default_factory=list)
    cdn_providers: list[str] = Field(default_factory=list)
    analytics_tools: list[str] = Field(default_factory=list)
    crm_tools: list[str] = Field(default_factory=list)

    # 招聘信号
    hiring_signals: list[HiringSignal] = Field(default_factory=list)
    is_hiring_engineers: bool = False
    is_hiring_ai_ml: bool = False
    is_hiring_sales: bool = False

    # 广告
    ad_platforms: list[str] = Field(default_factory=list)  # ["Google Ads", "Facebook Ads"]
    ad_budget_estimate: str = ""

    provenance: list[DataProvenance] = Field(default_factory=list)


class HiringSignal(BaseModel):
    """招聘信号 — 标识公司正在招聘某类人才"""
    job_title: str = ""
    department: str = ""
    location: str = ""
    posting_url: str = ""
    posted_date: str = ""
    is_active: bool = True
    relevance_to_bd: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# CRM
# ═══════════════════════════════════════════════════════════════════

class CRMAccountRef(BaseModel):
    """CRM 中的企业/客户引用"""
    crm_type: SourceType = SourceType.CRM_SALESFORCE
    crm_id: str = ""
    account_name: str = ""
    account_owner: str = ""
    stage: str = ""                        # lead / prospect / customer / churned
    annual_revenue: str = ""
    industry: str = ""
    last_activity_date: datetime | None = None
    notes: str = ""
    custom_fields: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
# Enrichment Request / Result
# ═══════════════════════════════════════════════════════════════════

class EnrichmentRequest(BaseModel):
    """一次 enrichment 请求 — 来自 ResearcherAgent"""
    request_id: str = ""

    # 输入
    company_name: str = ""
    domain: str = ""
    person_name: str = ""
    website: str = ""

    # 需求
    capabilities: list[str] = Field(default_factory=list)  # ["company_profile", "risk", "tech", "crm"]
    max_sources: int = 5
    max_cost: int = 100                                    # 最大消耗点数
    enforce_primary_source: bool = True                     # 必须至少有 1 个 primary source

    # 控制
    use_cache: bool = True
    dedup: bool = True
    trace_id: str = ""
    caller: str = "researcher"

    # 安全
    allow_crm_write: bool = False
    allowed_crm_fields: list[str] = Field(default_factory=list)


class EnrichmentResult(BaseModel):
    """一次 enrichment 的结果"""
    request: EnrichmentRequest

    # 企业画像
    identity: CompanyIdentity = Field(default_factory=CompanyIdentity)
    profile: CompanyProfile = Field(default_factory=CompanyProfile)
    risk: CompanyRiskProfile | None = None
    tech: CompanyTechProfile | None = None
    crm_refs: list[CRMAccountRef] = Field(default_factory=list)

    # 源记录
    source_records: list[SourceRecord] = Field(default_factory=list)

    # 合并决策
    merge_decisions: list[MergeDecision] = Field(default_factory=list)

    # 统计
    total_cost: int = 0                   # 消耗点数
    total_time_ms: float = 0
    sources_queried: int = 0
    sources_failed: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0

    # 元数据
    enriched_at: datetime = Field(default_factory=datetime.now)
    errors: list[str] = Field(default_factory=list)
    quality_score: float = 0.0            # 0-1, 综合可信度

    @property
    def has_primary_source(self) -> bool:
        """是否有 primary 级别的源"""
        return any(
            r.source_priority == SourcePriority.PRIMARY and not r.is_error
            for r in self.source_records
        )

    @property
    def summary(self) -> str:
        p = self.profile
        return (
            f"{p.identity.name} | {p.industry or 'N/A'} | "
            f"{p.status or 'N/A'} | {p.registered_capital or 'N/A'} | "
            f"quality={self.quality_score} | sources={self.sources_queried}"
        )


class MergeDecision(BaseModel):
    """多源数据合并决策记录"""
    field_name: str
    values: dict[SourceType, str] = Field(default_factory=dict)  # {source_type: value}
    chosen_source: SourceType | None = None
    chosen_value: str = ""
    conflict_detected: bool = False
    resolution: str = ""                   # "primary_wins" / "majority_vote" / "freshest" / "manual"
    reason: str = ""
    overridden: bool = False


# ═══════════════════════════════════════════════════════════════════
# Research Bundle (final output for downstream agents)
# ═══════════════════════════════════════════════════════════════════

class ResearchBundle(BaseModel):
    """ResearcherAgent 输出的完整研究包 — 供 Synthesizer/Strategist/Critic 消费"""

    # 身份
    company_name: str = ""
    identity: CompanyIdentity = Field(default_factory=CompanyIdentity)

    # 四个子画像
    profile: CompanyProfile = Field(default_factory=CompanyProfile)
    risk: CompanyRiskProfile | None = None
    tech: CompanyTechProfile | None = None
    crm_refs: list[CRMAccountRef] = Field(default_factory=list)

    # 网页研究 (Browser)
    browser_findings: list[dict[str, Any]] = Field(default_factory=list)

    # 人物
    person_profiles: list[dict[str, Any]] = Field(default_factory=list)

    # 溯源
    source_records: list[SourceRecord] = Field(default_factory=list)
    merge_decisions: list[MergeDecision] = Field(default_factory=list)

    # 质量
    quality_score: float = 0.0
    data_quality: str = "low"
    data_gaps: list[str] = Field(default_factory=list)   # missing fields
    warnings: list[str] = Field(default_factory=list)    # anomalies

    # LLM 推理结果
    llm_analysis: dict[str, Any] = Field(default_factory=dict)

    # 审计
    trace_id: str = ""
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def risk_summary(self) -> str:
        if not self.risk:
            return "no risk data"
        return (
            f"risk={self.risk.risk_score:.2f} ({self.risk.risk_level}) | "
            f"cases={self.risk.court_case_count} | "
            f"abnormal={self.risk.abnormal_operation_count}"
        )

    @property
    def for_synthesizer(self) -> dict[str, Any]:
        """SynthesizerAgent 消费的结构"""
        return {
            "company_name": self.company_name,
            "industry": self.profile.industry,
            "scale": {
                "employees": self.profile.employee_count_range,
                "revenue": self.profile.revenue_range,
                "registered_capital": self.profile.registered_capital,
            },
            "products": self.profile.products_services,
            "risk_level": self.risk.risk_level if self.risk else "unknown",
            "risk_score": self.risk.risk_score if self.risk else 0,
            "tech_stack": self.tech.detected_tech if self.tech else [],
            "crm_stage": self.crm_refs[0].stage if self.crm_refs else "unknown",
            "web_presence": len(self.browser_findings) > 0,
        }
