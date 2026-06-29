"""SLM — Small Language Model Tool Layer.

最小语言模型协同层: 将分类、抽取、重排、压缩、路由等高频子任务
下沉到小模型/启发式引擎，仅在高耦合/低置信度/复杂推理时升级到 LLM。

六种核心能力:
- RERANK   → 排序 (搜索结果、记忆片段、talking points)
- CLASSIFY → 分类 (意图、客户等级、风险、页面类型)
- EXTRACT  → 抽取 (公司名、人名、联系方式、风险标签)
- COMPRESS → 压缩 (长文本去重去噪提取关键句)
- ROUTE    → 路由 (意图 → tool/capability/agent)
- SCORE    → 评分 (置信度、文本质量、风险分)

使用方式:
    from byou.tools.slm import SLMGateway, SLMCapability

    gateway = SLMGateway()
    result = await gateway.rerank(query, candidates, top_k=3)
    if gateway.needs_llm(SLMCapability.RERANK, result):
        # escalate to LLM

推荐的 SLM-first 架构:
    1. SLM 处理 → confidence >= 阈值 → 直接使用结果
    2. SLM 置信度不足 → escalation → 大模型处理
    3. 事后分析 → SLM 结果作为对比 baseline
"""

from .types import (
    ClassificationLabel,
    ClassifyData,
    ClassifyResult,
    CompressData,
    CompressResult,
    EscalationConfig,
    ExtractData,
    ExtractResult,
    ExtractedField,
    MatchData,
    MatchResult,
    MatchedRecord,
    RankedItem,
    RerankData,
    RerankResult,
    RouteData,
    RouteResult,
    RouteTarget,
    ScoreData,
    ScoreResult,
    SLMCapability,
    SLMResult,
)

from .registry import SLMRegistry, get_registry
from .policies import SLMPolicies, PolicyDecision, quick_decision
from .gateway import SLMGateway, SLMStats, SLMInferenceCache
from .monitor import SLMPerformanceMonitor, InferenceRecord, get_monitor
from .reranker import Reranker
from .classifier import Classifier
from .extractor import Extractor
from .compressor import Compressor
from .router import Router
from .confidence import ConfidenceScorer

__all__ = [
    # Gateway
    "SLMGateway",
    "SLMStats",
    # Cache
    "SLMInferenceCache",
    # Monitor
    "SLMPerformanceMonitor",
    "InferenceRecord",
    "get_monitor",
    # Registry
    "SLMRegistry",
    "get_registry",
    # Policies
    "SLMPolicies",
    "PolicyDecision",
    "quick_decision",
    # Types
    "SLMCapability",
    "SLMResult",
    "RerankResult",
    "RerankData",
    "RankedItem",
    "ClassifyResult",
    "ClassifyData",
    "ClassificationLabel",
    "ExtractResult",
    "ExtractData",
    "ExtractedField",
    "CompressResult",
    "CompressData",
    "RouteResult",
    "RouteData",
    "RouteTarget",
    "ScoreResult",
    "ScoreData",
    "MatchResult",
    "MatchData",
    "MatchedRecord",
    "EscalationConfig",
    # Engines
    "Reranker",
    "Classifier",
    "Extractor",
    "Compressor",
    "Router",
    "ConfidenceScorer",
]
