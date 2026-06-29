"""SLM Types — small-model capability enumeration and result models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


# ── Capability ────────────────────────────────────────────────


class SLMCapability(str, Enum):
    """小模型能力枚举 — 所有 Agent 通过此枚举声明需求，不绑定模型名。"""
    RERANK = "rerank"
    CLASSIFY = "classify"
    EXTRACT = "extract"
    COMPRESS = "compress"
    SCORE = "score"
    ROUTE = "route"
    MATCH = "match"


# ── Base result ───────────────────────────────────────────────


T = TypeVar("T")


class SLMResult(BaseModel, Generic[T]):
    """统一的小模型返回类型。"""
    capability: SLMCapability
    model: str = ""                          # 实际使用的模型名
    data: T | None = None                    # 结果数据
    confidence: float = 0.0                  # [0.0, 1.0] 置信度
    latency_ms: float = 0.0                  # 延迟
    needs_escalation: bool = False           # 是否需要升级到大模型
    escalation_reason: str = ""              # 升级原因
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.7 and not self.needs_escalation


# ── Rerank result ─────────────────────────────────────────────


class RankedItem(BaseModel):
    id: str = ""
    text: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RerankData(BaseModel):
    items: list[RankedItem] = Field(default_factory=list)
    query: str = ""
    candidates_count: int = 0


RerankResult = SLMResult[RerankData]


# ── Classify result ───────────────────────────────────────────


class ClassificationLabel(BaseModel):
    label: str
    score: float = 0.0
    rationale: str = ""


class ClassifyData(BaseModel):
    labels: list[ClassificationLabel] = Field(default_factory=list)
    top_label: str = ""
    top_score: float = 0.0
    is_multi_label: bool = False


ClassifyResult = SLMResult[ClassifyData]


# ── Extract result ────────────────────────────────────────────


class ExtractedField(BaseModel):
    field_name: str
    value: str = ""
    confidence: float = 0.0
    source_span: str = ""


class ExtractData(BaseModel):
    fields: list[ExtractedField] = Field(default_factory=list)
    text_length: int = 0
    fields_found: int = 0


ExtractResult = SLMResult[ExtractData]


# ── Compress result ───────────────────────────────────────────


class CompressData(BaseModel):
    compressed_text: str = ""
    original_length: int = 0
    compressed_length: int = 0
    key_sentences: list[str] = Field(default_factory=list)


CompressResult = SLMResult[CompressData]


# ── Route result ──────────────────────────────────────────────


class RouteTarget(BaseModel):
    target: str = ""           # capability / tool / agent name
    score: float = 0.0
    rationale: str = ""


class RouteData(BaseModel):
    targets: list[RouteTarget] = Field(default_factory=list)
    intent: str = ""
    top_target: str = ""


RouteResult = SLMResult[RouteData]


# ── Match result ──────────────────────────────────────────────


class MatchedRecord(BaseModel):
    record_id: str = ""
    score: float = 0.0
    summary: str = ""
    relevance_rationale: str = ""


class MatchData(BaseModel):
    matches: list[MatchedRecord] = Field(default_factory=list)
    query: str = ""
    pool_size: int = 0


MatchResult = SLMResult[MatchData]


# ── Score result ──────────────────────────────────────────────


class ScoreData(BaseModel):
    score: float = 0.0
    sub_scores: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


ScoreResult = SLMResult[ScoreData]


# ── Escalation config ─────────────────────────────────────────


class EscalationConfig(BaseModel):
    """SLM → LLM 升级配置"""
    min_confidence: float = 0.6
    max_latency_ms: float = 500.0
    max_label_count: int = 5
    enable_fallback: bool = True
    fallback_uses_llm: bool = True
