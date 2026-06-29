"""Enrichment Subsystem — Byou 商务数据接入与 Enrichment 层。

将 MCP Tool Bus 和 Browser Research 组合为商务情报多源 enrichment。

核心组件:
- EnrichmentOrchestrator — 多源编排引擎
- TianYanChaAdapter — 天眼查 (PRIMARY)
- CRMAdapter — CRM (PRIMARY, 只读优先)
- BrowserBridgeAdapter — 网页研究桥接 (FALLBACK)
- IdentityResolver — 企业身份解析
- DataMerger — 多源归一化/去重/合并
- MergePolicy — 字段级冲突解决

架构:
    ResearcherAgent
        │ EnrichmentRequest(capabilities=["company_profile","company_risk"])
        ▼
    EnrichmentOrchestrator
        ├── TianYanChaAdapter  ── PRIMARY    (工商+风险)
        ├── CRMAdapter         ── PRIMARY    (CRM记录, 只读)
        ├── OpenSalesStack     ── SECONDARY  (技术栈+招聘, 待实现)
        └── BrowserBridge      ── FALLBACK   (网页补充)
        │
        ▼
    DataMerger  ── 归一化 + 去重 + provenance
        │
        ▼
    EnrichmentResult
        │ to_bundle()
        ▼
    ResearchBundle  ── 供 Synthesizer / Strategist / Critic 消费
"""

from byou.tools.enrichment.types import (
    SourceType, SourcePriority, SourceRecord,
    CompanyIdentity, CompanyProfile, CompanyRiskProfile, CompanyTechProfile,
    HiringSignal, CRMAccountRef,
    EnrichmentRequest, EnrichmentResult, ResearchBundle,
    DataProvenance, MergeDecision,
)

from byou.tools.enrichment.policies import (
    SOURCE_PRIORITY_MAP, SOURCE_CAPABILITY_MAP, SOURCE_COST_MAP,
    FALLBACK_CHAIN, MergePolicy, QuotaPolicy,
)

from byou.tools.enrichment.identity import IdentityResolver, DomainResolver
from byou.tools.enrichment.merger import DataMerger
from byou.tools.enrichment.orchestrator import EnrichmentOrchestrator

from byou.tools.enrichment.adapters.tianyancha import TianYanChaAdapter
from byou.tools.enrichment.adapters.browser_bridge import BrowserBridgeAdapter
from byou.tools.enrichment.adapters.crm_adapter import CRMAdapter

__all__ = [
    # Types
    "SourceType", "SourcePriority", "SourceRecord",
    "CompanyIdentity", "CompanyProfile", "CompanyRiskProfile", "CompanyTechProfile",
    "HiringSignal", "CRMAccountRef",
    "EnrichmentRequest", "EnrichmentResult", "ResearchBundle",
    "DataProvenance", "MergeDecision",
    # Policies
    "SOURCE_PRIORITY_MAP", "SOURCE_CAPABILITY_MAP", "SOURCE_COST_MAP",
    "FALLBACK_CHAIN", "MergePolicy", "QuotaPolicy",
    # Engine
    "IdentityResolver", "DomainResolver",
    "DataMerger",
    "EnrichmentOrchestrator",
    # Adapters
    "TianYanChaAdapter", "BrowserBridgeAdapter", "CRMAdapter",
]
