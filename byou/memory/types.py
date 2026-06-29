"""Byou Memory — 强类型数据模型 (零 dict)。

五层记忆系统 + 知识图谱节点/边 + 案例匹配 + 策略记忆。

设计原则:
- 所有数据结构 Pydantic 强类型
- 零 dict 传递
- 完整的 model_dump/model_validate 序列化
- 支持时间戳、置信度、来源追溯
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════
# Memory Tiers — 五层记忆
# ════════════════════════════════════════════════════════

class MemoryTier(str, Enum):
    WORKING = "working"        # Pipeline 上下文
    SESSION = "session"         # 会话内积累
    LONG_TERM = "long_term"     # 向量存储
    GRAPH = "graph"             # 知识图谱
    STRATEGY = "strategy"       # 策略模式


class DataCategory(str, Enum):
    """数据类别，决定存储和遗忘策略"""
    PERMANENT = "permanent"       # 永久保留 (工商信息、股权)
    STABLE = "stable"             # 稳定但可更新 (公司简介、行业)
    VOLATILE = "volatile"         # 易变 (新闻、舆情)
    INFERRED = "inferred"         # LLM 推理产物 (可过期)
    STRATEGY = "strategy"         # 策略模式


class MemoryEntry(BaseModel):
    """记忆条目基底"""
    id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:12]}")
    tier: MemoryTier
    category: DataCategory
    key: str                                # 唯一标识键
    content: dict[str, Any]                 # 序列化的结构化数据
    embedding: list[float] | None = None    # 向量 (可选)
    metadata: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source: str = ""                        # "enrichment_l4" | "browser_l3" | "llm_inference"
    source_pipeline_id: str = ""            # 产生该记忆的 Pipeline ID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    ttl_seconds: int | None = None          # None=永不过期
    is_archived: bool = False

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.ttl_seconds is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - self.created_at).total_seconds() > self.ttl_seconds


class MemoryQuery(BaseModel):
    """记忆查询"""
    query_text: str = ""
    query_embedding: list[float] | None = None
    tier: MemoryTier | None = None
    category: DataCategory | None = None
    top_k: int = Field(default=10, ge=1, le=100)
    min_confidence: float = 0.0
    exclude_archived: bool = True


class MemoryQueryResult(BaseModel):
    """记忆查询结果"""
    entries: list[MemoryEntry] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)  # 1:1 with entries
    query_time_ms: float = 0
    total_hits: int = 0


# ════════════════════════════════════════════════════════
# Working Memory — 单次 Pipeline
# ════════════════════════════════════════════════════════

class WorkingMemory(BaseModel):
    """单次 Pipeline 执行期间的活跃上下文"""
    pipeline_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    company_name: str = ""
    person_name: str = ""
    extracted: dict[str, Any] = Field(default_factory=dict)    # Extractor 输出
    enriched: dict[str, Any] = Field(default_factory=dict)     # Enrichment 输出
    browser: dict[str, Any] = Field(default_factory=dict)      # Browser 输出
    research: dict[str, Any] = Field(default_factory=dict)     # Researcher 输出
    initial_strategy: dict[str, Any] = Field(default_factory=dict)  # Strategist 草稿
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)  # 工具调用日志
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)   # Agent 间传递的备注
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def snapshot(self) -> MemoryEntry:
        return MemoryEntry(
            tier=MemoryTier.WORKING,
            category=DataCategory.INFERRED,
            key=f"working_{self.pipeline_id}",
            content=self.model_dump(),
            ttl_seconds=3600,
        )


# ════════════════════════════════════════════════════════
# Session Memory — 当前会话内
# ════════════════════════════════════════════════════════

class SessionMemory(BaseModel):
    """会话级积累 — 当天多次 Pipeline 之间共享"""
    session_id: str = Field(default_factory=lambda: f"ses_{uuid.uuid4().hex[:8]}")
    recent_companies: list[str] = Field(default_factory=list)
    recent_pipelines: list[str] = Field(default_factory=list)  # pipeline_ids
    discoveries: list[dict[str, Any]] = Field(default_factory=list)  # 重要发现
    cross_references: list[dict[str, Any]] = Field(default_factory=list)  # 交叉引用
    todays_insights: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def snapshot(self) -> MemoryEntry:
        return MemoryEntry(
            tier=MemoryTier.SESSION,
            category=DataCategory.VOLATILE,
            key=f"session_{self.session_id}",
            content=self.model_dump(),
            ttl_seconds=86400,  # 1 天
        )


# ════════════════════════════════════════════════════════
# Long-Term Memory — 向量存储的企业档案
# ════════════════════════════════════════════════════════

class LongTermMemory(BaseModel):
    """持久化企业档案 (向量存储中的单条)"""
    company_name: str
    company_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    unified_social_credit_code: str = ""
    profile_summary: str = ""               # 用于向量化的摘要文本
    profile_json: dict[str, Any] = Field(default_factory=dict)  # 完整 CompanyProfile
    risk_json: dict[str, Any] | None = None  # CompanyRiskProfile
    industry: str = ""
    employee_range: str = ""
    revenue_range: str = ""
    risk_score: float = 0.0
    last_researched_at: datetime | None = None
    research_count: int = 0
    tags: list[str] = Field(default_factory=list)
    key_people: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    bd_notes: str = ""                      # 商务笔记

    def to_profile_text(self) -> str:
        """生成用于向量嵌入的文本"""
        parts = [
            f"Company: {self.company_name}",
            f"Industry: {self.industry}",
            f"Scale: {self.employee_range}",
            f"Revenue: {self.revenue_range}",
            f"Risk: {self.risk_score}",
        ]
        if self.profile_summary:
            parts.append(f"Summary: {self.profile_summary}")
        if self.bd_notes:
            parts.append(f"BD Notes: {self.bd_notes}")
        return "\n".join(parts)

    def to_memory_entry(self) -> MemoryEntry:
        return MemoryEntry(
            tier=MemoryTier.LONG_TERM,
            category=DataCategory.STABLE,
            key=f"company_{self.company_name}",
            content=self.model_dump(),
            metadata={
                "company_name": self.company_name,
                "industry": self.industry,
                "risk_score": str(self.risk_score),
            },
            ttl_seconds=None,  # 不自动过期
        )


# ════════════════════════════════════════════════════════
# Knowledge Graph — 节点 & 边
# ════════════════════════════════════════════════════════

class NodeType(str, Enum):
    COMPANY = "company"
    PERSON = "person"
    INDUSTRY = "industry"
    PRODUCT = "product"
    EVENT = "event"
    BD_CONTACT = "bd_contact"
    INSIGHT = "insight"


class EdgeType(str, Enum):
    EMPLOYS = "employs"
    EMPLOYED_BY = "employed_by"
    COMPETES_WITH = "competes_with"
    SUPPLIES_TO = "supplies_to"
    SUPPLIED_BY = "supplied_by"
    INVESTS_IN = "invests_in"
    INVESTED_BY = "invested_by"
    PARTICIPATED_IN = "participated_in"
    LOCATED_IN = "located_in"
    BELONGS_TO_INDUSTRY = "belongs_to_industry"
    HAS_CONTACT = "has_contact"
    SIMILAR_TO = "similar_to"
    DERIVED_FROM = "derived_from"


class GraphNode(BaseModel):
    """图谱节点基底"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    node_type: NodeType
    name: str                               # 显示名
    properties: dict[str, Any] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)  # source IDs
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int | None = None

    def key(self) -> str:
        return f"{self.node_type.value}:{self.name}"


class GraphEdge(BaseModel):
    """图谱边基底"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    edge_type: EdgeType
    source_node_id: str
    target_node_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence: str = ""                      # LLM 给出的关系证据
    is_bidirectional: bool = False

    def key(self) -> str:
        return f"{self.edge_type.value}:{self.source_node_id}->{self.target_node_id}"


# ── 具体节点类型 ─────────────────────────────────

class CompanyNode(GraphNode):
    node_type: NodeType = NodeType.COMPANY
    unified_social_credit_code: str = ""
    industry: str = ""
    employee_range: str = ""
    revenue_range: str = ""
    risk_score: float = 0.0
    status: str = ""


class PersonNode(GraphNode):
    node_type: NodeType = NodeType.PERSON
    title: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    wechat: str = ""


class IndustryNode(GraphNode):
    node_type: NodeType = NodeType.INDUSTRY
    category: str = ""
    subcategory: str = ""


class ProductNode(GraphNode):
    node_type: NodeType = NodeType.PRODUCT
    company: str = ""
    description: str = ""


class EventNode(GraphNode):
    node_type: NodeType = NodeType.EVENT
    event_type: str = ""    # "funding" | "lawsuit" | "ipo" | "acquisition"
    date: str = ""
    description: str = ""
    amount_yuan: float = 0.0


class BDContactNode(GraphNode):
    node_type: NodeType = NodeType.BD_CONTACT
    contact_type: str = ""  # "email" | "phone" | "wechat" | "linkedin"
    value: str = ""
    owner_company: str = ""
    owner_person: str = ""


class InsightNode(GraphNode):
    node_type: NodeType = NodeType.INSIGHT
    content: str = ""
    insight_type: str = ""  # "strategy" | "market" | "risk" | "opportunity"
    related_entities: list[str] = Field(default_factory=list)  # node_ids


# ── 具体边类型 ──────────────────────────────────

class EmploysEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.EMPLOYS

class CompetesWithEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.COMPETES_WITH
    competition_type: str = ""  # "direct" | "indirect" | "potential"

class SuppliesToEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.SUPPLIES_TO
    product: str = ""

class InvestsInEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.INVESTS_IN
    amount_yuan: float = 0.0
    stake_percent: float = 0.0

class ParticipatedInEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.PARTICIPATED_IN
    role: str = ""  # "plaintiff" | "defendant" | "investor" | "attendee"

class LocatedInEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.LOCATED_IN
    address: str = ""

class BelongsToIndustryEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.BELONGS_TO_INDUSTRY

class HasContactEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.HAS_CONTACT

class SimilarToEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.SIMILAR_TO
    similarity_score: float = 0.0

class DerivedFromEdge(GraphEdge):
    edge_type: EdgeType = EdgeType.DERIVED_FROM
    derivation_rule: str = ""


# ════════════════════════════════════════════════════════
# Case Matching — 历史案例相似匹配
# ════════════════════════════════════════════════════════

class SimilarCase(BaseModel):
    """历史相似案例"""
    rank: int
    company_name: str
    similarity_score: float
    match_reasons: list[str] = Field(default_factory=list)
    profile: LongTermMemory | None = None
    strategy: "StrategyMemory | None" = None   # 该案例的策略
    outcome: str = ""                           # "won" | "lost" | "pending" | "unknown"
    notes: str = ""


class CaseQuery(BaseModel):
    """案例匹配查询"""
    company_name: str
    company_profile: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    include_strategies: bool = True
    industry_weight: float = 0.3
    scale_weight: float = 0.2
    risk_weight: float = 0.15
    semantic_weight: float = 0.35


class CaseQueryResult(BaseModel):
    """案例匹配结果"""
    query: CaseQuery
    cases: list[SimilarCase] = Field(default_factory=list)
    query_time_ms: float = 0
    total_candidates_searched: int = 0


class CompanyVector(BaseModel):
    """企业向量表示 (用于相似度计算)"""
    company_name: str
    vector: list[float]
    industry: str = ""
    employee_range: str = ""
    risk_score: float = 0.0
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ════════════════════════════════════════════════════════
# Strategy Memory — Learning Loop 蒸馏
# ════════════════════════════════════════════════════════

class StrategyCondition(BaseModel):
    """策略适用条件"""
    field: str                              # 字段名
    operator: str                           # "equals" | "contains" | "range" | "gt" | "lt"
    value: Any
    weight: float = 1.0


class StrategyPattern(BaseModel):
    """抽象策略模式"""
    id: str = Field(default_factory=lambda: f"pat_{uuid.uuid4().hex[:8]}")
    name: str                               # 策略名称
    description: str                        # 策略描述
    conditions: list[StrategyCondition] = Field(default_factory=list)
    template: str                           # 策略话术模板
    applicable_industries: list[str] = Field(default_factory=list)
    applicable_scales: list[str] = Field(default_factory=list)
    success_count: int = 0
    total_count: int = 0
    avg_effectiveness: float = 0.0
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    insights: list[str] = Field(default_factory=list)
    version: int = 1

    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count


class StrategyMemory(BaseModel):
    """策略记忆 — Learning Loop 的长期产物"""
    id: str = Field(default_factory=lambda: f"strm_{uuid.uuid4().hex[:12]}")
    company_context: dict[str, Any] = Field(default_factory=dict)
    strategy_json: dict[str, Any] = Field(default_factory=dict)
    outcome: str = ""                       # "won" | "lost" | "pending" | "unknown"
    effectiveness_score: float = 0.0
    extracted_patterns: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    key_factors: list[str] = Field(default_factory=list)
    industry: str = ""
    company_scale: str = ""
    risk_level: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_id: str = ""
    version: int = 1

    def to_memory_entry(self) -> MemoryEntry:
        return MemoryEntry(
            tier=MemoryTier.STRATEGY,
            category=DataCategory.STRATEGY,
            key=f"strategy_{self.id}",
            content=self.model_dump(),
            ttl_seconds=None,
        )
