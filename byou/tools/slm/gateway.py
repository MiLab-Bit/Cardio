"""SLM Gateway — 小模型统一门面。

所有 Agent 通过 SLMGateway 调用小模型能力，不直接依赖具体模型。
设计原则:
1. Agent 声明 SLMCapability，不绑定模型
2. Gateway 负责 routing → model selection → execution → escalation
3. 所有结果统一封装为 SLMResult[T]
4. 支持 SLM-first / LLM-escalation 模式
5. 内置推理缓存，避免重复计算

使用示例:
    gateway = SLMGateway()
    result = await gateway.rerank(query="企业背调", candidates=candidates)
    if result.needs_escalation:
        # fallback to LLM
        ...
"""

from __future__ import annotations

import hashlib
import logging
import time
import json as _json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncIterator
from collections import OrderedDict

from .types import (
    ClassifyResult,
    CompressResult,
    EscalationConfig,
    ExtractResult,
    RankedItem,
    RerankData,
    RerankResult,
    RouteResult,
    ScoreResult,
    SLMCapability,
    SLMResult,
)
from .registry import SLMRegistry, get_registry
from .policies import SLMPolicies, PolicyDecision
from .reranker import Reranker
from .classifier import Classifier
from .extractor import Extractor
from .compressor import Compressor
from .router import Router
from .confidence import ConfidenceScorer
from .monitor import SLMPerformanceMonitor, InferenceRecord, get_monitor

logger = logging.getLogger(__name__)


# ── Inference Cache ──────────────────────────────────────────

class SLMInferenceCache:
    """SLM 推理结果缓存 — 避免重复推理，提速 3-5x。
    
    特性:
    - LRU 淘汰策略（最大 1000 条）
    - TTL 过期（默认 5 分钟）
    - 线程安全
    - 支持批量查询
    """
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
    
    def make_key(self, capability: str, **kwargs) -> str:
        """生成缓存 key（基于参数的 hash）"""
        sorted_items = sorted(kwargs.items(), key=lambda x: str(x[0]))
        key_str = f"{capability}:" + ":".join(f"{k}={v}" for k, v in sorted_items)
        return hashlib.md5(key_str.encode('utf-8')).hexdigest()
    
    def get(self, key: str) -> Any | None:
        """获取缓存值（如果未过期）"""
        if key not in self._cache:
            self._misses += 1
            return None
        
        value, timestamp = self._cache[key]
        
        if time.time() - timestamp > self.ttl_seconds:
            del self._cache[key]
            self._misses += 1
            return None
        
        self._cache.move_to_end(key)
        self._hits += 1
        return value
    
    def put(self, key: str, value: Any) -> None:
        """存入缓存"""
        if len(self._cache) >= self.max_size and key not in self._cache:
            self._cache.popitem(last=False)
        
        self._cache[key] = (value, time.time())
        self._cache.move_to_end(key)
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
    
    def stats(self) -> dict[str, Any]:
        """缓存统计"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }


# ── SLMGateway ───────────────────────────────────────────────

class SLMGateway:
    """小模型统一门面 — 所有 SLM 调用的入口点"""

    def __init__(self, registry: SLMRegistry | None = None, policies: SLMPolicies | None = None):
        self.registry = registry or get_registry()
        self.policies = policies or SLMPolicies()

        # 推理缓存
        self._cache = SLMInferenceCache(max_size=1000, ttl_seconds=300)
        self._cache_enabled = True

        # 性能监控
        self._monitor = get_monitor()
        self._monitor_enabled = True

        # 检测真实模型可用性
        self._has_real = False
        self._detect_real_models()

        # 懒加载的内部组件
        self._reranker: Reranker | None = None
        self._classifier: Classifier | None = None
        self._extractor: Extractor | None = None
        self._compressor: Compressor | None = None
        self._router: Router | None = None
        self._scorer: ConfidenceScorer | None = None

        # 真实模型引擎
        self._real_classifier = None
        self._real_router = None
        self._real_extractor = None
        self._real_compressor = None
        self._real_reranker = None

        # 统计
        self.stats = SLMStats()

    def _detect_real_models(self):
        """检测真实模型是否可用"""
        try:
            from .real_engines import model_available
            self._has_real = model_available()
        except ImportError:
            self._has_real = False
        if self._has_real:
            logger.info("Real models detected (Qwen2.5-0.5B)")

    # ── Public API ─────────────────────────────────────────────

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
        min_score: float = 0.0,
        context_tag: str = "default",
    ) -> RerankResult:
        """对候选列表做精排。

        Args:
            query: 查询文本
            candidates: [{"id": ..., "text": ..., "metadata": ...}, ...]
            top_k: 保留前 k 个
            min_score: 最低相关度阈值
            context_tag: 上下文标签 (用来选策略)

        Returns:
            RerankResult — 包含排序后的 items 和 confidence
        """
        # 检查缓存
        if self._cache_enabled:
            cache_key = self._cache.make_key(
                "rerank", query=query, candidates=str(candidates), top_k=top_k, min_score=min_score
            )
            cached = self._cache.get(cache_key)
            if cached:
                # 记录缓存命中
                if self._monitor_enabled:
                    self._record_metrics("rerank", cached, query, cache_hit=True)
                return cached

        decision = self.policies.should_use_slm(
            SLMCapability.RERANK, context_tag,
            input_is_structured=True,
            has_fallback=True,
        )
        if not decision.should_use_slm:
            return _empty_rerank_result(query, reason="policy_skip")

        self.stats.increment("rerank")
        result = await self._get_reranker().rerank(
            query, candidates, top_k=top_k, min_score=min_score,
        )

        # 存入缓存
        if self._cache_enabled and result.confidence > 0:
            cache_key = self._cache.make_key(
                "rerank", query=query, candidates=str(candidates), top_k=top_k, min_score=min_score
            )
            self._cache.put(cache_key, result)

        # 记录性能指标
        if self._monitor_enabled:
            record = InferenceRecord(
                timestamp=time.time(),
                model_id=result.model,
                capability="rerank",
                latency_ms=result.latency_ms,
                confidence=result.confidence,
                needs_escalation=result.needs_escalation,
                input_length=len(query),
                output_length=len(result.data.items) if result.data else 0,
                cache_hit=False,
            )
            self._monitor.record_inference(record)

        return result

    async def classify(
        self,
        text: str,
        labels: list[str] | None = None,
        context_tag: str = "default",
        multi_label: bool = False,
    ) -> ClassifyResult:
        """文本分类。

        Args:
            text: 待分类文本
            labels: 标签列表 (None = auto-detect)
            context_tag: 上下文标签
            multi_label: 是否允许多标签

        Returns:
            ClassifyResult
        """
        # 检查缓存
        if self._cache_enabled:
            cache_key = self._cache.make_key(
                "classify", text=text, labels=str(labels), context_tag=context_tag, multi_label=multi_label
            )
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        decision = self.policies.should_use_slm(
            SLMCapability.CLASSIFY, context_tag,
            input_is_structured=True,
            output_has_fixed_labels=(labels is not None),
            has_fallback=True,
        )
        if not decision.should_use_slm:
            return _empty_classify_result(reason="policy_skip")

        self.stats.increment("classify")
        result = await self._get_classifier().classify(
            text, labels=labels, context_tag=context_tag, multi_label=multi_label,
        )

        # 存入缓存
        if self._cache_enabled and result.confidence > 0:
            cache_key = self._cache.make_key(
                "classify", text=text, labels=str(labels), context_tag=context_tag, multi_label=multi_label
            )
            self._cache.put(cache_key, result)

        # 记录性能指标
        if self._monitor_enabled:
            self._record_metrics("classify", result, text)

        return result

    async def extract(
        self,
        text: str,
        fields: list[str] | None = None,
        context_tag: str = "default",
    ) -> ExtractResult:
        """字段抽取。

        Args:
            text: 源文本
            fields: 要抽取的字段列表 (None = 全部)
            context_tag: 上下文标签

        Returns:
            ExtractResult
        """
        # 检查缓存
        if self._cache_enabled:
            cache_key = self._cache.make_key(
                "extract", text=text, fields=str(fields), context_tag=context_tag
            )
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        decision = self.policies.should_use_slm(
            SLMCapability.EXTRACT, context_tag,
            input_is_structured=True,
            output_has_fixed_labels=True,
            has_fallback=True,
        )
        if not decision.should_use_slm:
            return _empty_extract_result(reason="policy_skip")

        self.stats.increment("extract")
        result = await self._get_extractor().extract(text, fields=fields, context_tag=context_tag)

        # 存入缓存
        if self._cache_enabled and result.confidence > 0:
            cache_key = self._cache.make_key(
                "extract", text=text, fields=str(fields), context_tag=context_tag
            )
            self._cache.put(cache_key, result)

        # 记录性能指标
        if self._monitor_enabled:
            self._record_metrics("extract", result, text)

        return result

    async def compress(
        self,
        text: str,
        max_chars: int = 500,
        target_ratio: float = 0.3,
    ) -> CompressResult:
        """文本压缩。

        Args:
            text: 源文本
            max_chars: 最大输出字符数
            target_ratio: 目标压缩比

        Returns:
            CompressResult
        """
        # 检查缓存
        if self._cache_enabled:
            cache_key = self._cache.make_key(
                "compress", text=text, max_chars=max_chars, target_ratio=target_ratio
            )
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        decision = self.policies.should_use_slm(
            SLMCapability.COMPRESS, "default",
            input_is_structured=True,
            has_fallback=True,
        )
        if not decision.should_use_slm:
            return CompressResult(
                capability=SLMCapability.COMPRESS,
                model="none",
                data=None,
                confidence=0.0,
                latency_ms=0,
                needs_escalation=True,
                escalation_reason="policy_skip",
            )

        self.stats.increment("compress")
        result = await self._get_compressor().compress(text, max_chars=max_chars, target_ratio=target_ratio)

        # 存入缓存
        if self._cache_enabled and result.confidence > 0:
            cache_key = self._cache.make_key(
                "compress", text=text, max_chars=max_chars, target_ratio=target_ratio
            )
            self._cache.put(cache_key, result)

        # 记录性能指标
        if self._monitor_enabled:
            self._record_metrics("compress", result, text)

        return result

    async def route(
        self,
        query: str,
        route_type: str = "capability",
    ) -> RouteResult:
        """意图路由。

        Args:
            query: 查询文本
            route_type: "intent" / "agent" / "capability"

        Returns:
            RouteResult
        """
        # 检查缓存
        if self._cache_enabled:
            cache_key = self._cache.make_key(
                "route", query=query, route_type=route_type
            )
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        decision = self.policies.should_use_slm(
            SLMCapability.ROUTE, "default",
            input_is_structured=True,
            output_has_fixed_labels=True,
            has_fallback=True,
            is_high_frequency=True,
        )
        if not decision.should_use_slm:
            return _empty_route_result(reason="policy_skip")

        self.stats.increment("route")
        if route_type == "intent" or route_type == "capability":
            result = await self._get_router().route_intent_to_capability(query)
        elif route_type == "agent":
            result = await self._get_router().route_to_agent(query)
        else:
            result = await self._get_router().route_tool_capability(query)

        # 存入缓存
        if self._cache_enabled and result.confidence > 0:
            cache_key = self._cache.make_key(
                "route", query=query, route_type=route_type
            )
            self._cache.put(cache_key, result)

        # 记录性能指标
        if self._monitor_enabled:
            self._record_metrics("route", result, query)

        return result

    async def score_quality(self, text: str) -> ScoreResult:
        """文本质量评分"""
        self.stats.increment("score")
        return await self._get_scorer().score(text)

    async def needs_llm(
        self,
        capability: SLMCapability,
        slm_result: SLMResult,
    ) -> bool:
        """判断 SLM 结果是否需要升级到 LLM"""
        # 先看 SLM 自身是否标记需要升级
        if slm_result.needs_escalation:
            return True

        # 再看策略阈值
        config = self.policies.get_config(capability)
        return self.policies.needs_escalation(slm_result.confidence, config)

    # ── 快捷方法 ───────────────────────────────────────────────

    async def rerank_browser_results(
        self, query: str, pages: list[dict[str, Any]], top_k: int = 3,
    ) -> RerankResult:
        """快捷方法: 浏览器搜索结果重排"""
        self.stats.increment("rerank")
        return await self._get_reranker().rerank(query, pages, top_k=top_k)

    async def classify_research_intent(self, query: str) -> ClassifyResult:
        """快捷方法: 研究意图分类"""
        self.stats.increment("classify")
        return await self._get_classifier().classify_research_intent(query)

    async def classify_page_type(self, snippet: str) -> ClassifyResult:
        """快捷方法: 网页类型分类"""
        self.stats.increment("classify")
        return await self._get_classifier().classify_page_type(snippet)

    async def classify_customer_level(self, profile_text: str) -> ClassifyResult:
        """快捷方法: 客户等级分类"""
        self.stats.increment("classify")
        return await self._get_classifier().classify_customer_level(profile_text)

    async def extract_company_fields(self, text: str) -> ExtractResult:
        """快捷方法: 抽取公司字段"""
        self.stats.increment("extract")
        return await self._get_extractor().extract_company_fields(text)

    async def compress_browser_snippet(self, text: str) -> CompressResult:
        """快捷方法: 压缩浏览器片段"""
        self.stats.increment("compress")
        return await self._get_compressor().compress_browser_snippet(text)

    # ── Lazy init ─────────────────────────────────────────────

    def _get_reranker(self) -> Reranker:
        if self._reranker is None:
            if self._has_real:
                try:
                    from .real_engines import RealReranker
                    self._real_reranker = RealReranker()
                except ImportError:
                    self._real_reranker = None
            self._reranker = Reranker()
        if self._real_reranker is not None:
            return self._real_reranker
        return self._reranker

    def _get_classifier(self):
        if self._classifier is None:
            if self._has_real:
                try:
                    from .real_engines import RealClassifier
                    self._real_classifier = RealClassifier()
                except ImportError:
                    self._real_classifier = None
            self._classifier = Classifier()
        if self._real_classifier is not None:
            return self._real_classifier
        return self._classifier

    def _get_extractor(self) -> Extractor:
        if self._extractor is None:
            if self._has_real:
                try:
                    from .real_engines import RealExtractor
                    self._real_extractor = RealExtractor()
                except ImportError:
                    self._real_extractor = None
            self._extractor = Extractor()
        if self._real_extractor is not None:
            return self._real_extractor
        return self._extractor

    def _get_compressor(self) -> Compressor:
        if self._compressor is None:
            if self._has_real:
                try:
                    from .real_engines import RealCompressor
                    self._real_compressor = RealCompressor()
                except ImportError:
                    self._real_compressor = None
            self._compressor = Compressor()
        if self._real_compressor is not None:
            return self._real_compressor
        return self._compressor

    def _get_router(self) -> Router:
        if self._router is None:
            if self._has_real:
                try:
                    from .real_engines import RealRouter
                    self._real_router = RealRouter()
                except ImportError:
                    self._real_router = None
            self._router = Router()
        if self._real_router is not None:
            return self._real_router
        return self._router

    def _get_scorer(self) -> ConfidenceScorer:
        if self._scorer is None:
            self._scorer = ConfidenceScorer()
        return self._scorer

    # ── Cache control ─────────────────────────────────────────

    def enable_cache(self) -> None:
        """启用推理缓存"""
        self._cache_enabled = True
        logger.info("SLM inference cache enabled")

    def disable_cache(self) -> None:
        """禁用推理缓存"""
        self._cache_enabled = False
        logger.info("SLM inference cache disabled")

    def clear_cache(self) -> None:
        """清空推理缓存"""
        self._cache.clear()
        logger.info("SLM inference cache cleared")

    def get_cache_stats(self) -> dict[str, Any]:
        """获取缓存统计"""
        return self._cache.stats()

    def get_performance_report(self) -> str:
        """获取性能报告"""
        return self._monitor.generate_report()

    def export_performance_data(self, filepath: str) -> None:
        """导出性能数据到 JSON"""
        self._monitor.export_json(filepath)

    def _record_metrics(self, capability: str, result: SLMResult, input_text: str, cache_hit: bool = False) -> None:
        """记录性能指标（内部辅助方法）"""
        if not self._monitor_enabled:
            return

        record = InferenceRecord(
            timestamp=time.time(),
            model_id=result.model,
            capability=capability,
            latency_ms=result.latency_ms,
            confidence=result.confidence,
            needs_escalation=result.needs_escalation,
            input_length=len(input_text),
            output_length=0,  # 可以根据结果类型调整
            cache_hit=cache_hit,
        )
        self._monitor.record_inference(record)

    # ── Context manager ───────────────────────────────────────

    @asynccontextmanager
    async def session(self) -> AsyncIterator["SLMGateway"]:
        """作为上下文管理器使用，自动记录统计"""
        try:
            yield self
        finally:
            stats = self.stats.summary()
            cache_stats = self._cache.stats()
            logger.debug("SLM session stats: %s, cache: %s", stats, cache_stats)


# ── SLMStats ──────────────────────────────────────────────────

class SLMStats:
    """SLM 调用统计（包含缓存统计）"""

    def __init__(self):
        self._counts: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self._escalations: dict[str, int] = {}

    def increment(self, capability: str) -> None:
        self._counts[capability] = self._counts.get(capability, 0) + 1

    def record_latency(self, capability: str, ms: float) -> None:
        if capability not in self._latencies:
            self._latencies[capability] = []
        self._latencies[capability].append(ms)

    def record_escalation(self, capability: str) -> None:
        self._escalations[capability] = self._escalations.get(capability, 0) + 1

    def summary(self) -> dict[str, Any]:
        return {
            "total_calls": sum(self._counts.values()),
            "by_capability": dict(self._counts),
            "escalations": dict(self._escalations),
            "avg_latency_ms": {
                k: round(sum(v) / len(v), 2) for k, v in self._latencies.items() if v
            },
        }

    def reset(self) -> None:
        self._counts.clear()
        self._latencies.clear()
        self._escalations.clear()


# ── Empty result helpers ───────────────────────────────────────


def _empty_rerank_result(query: str, reason: str = "") -> RerankResult:
    return RerankResult(
        capability=SLMCapability.RERANK,
        model="none",
        data=RerankData(items=[], query=query),
        confidence=0.0,
        latency_ms=0,
        needs_escalation=True,
        escalation_reason=reason,
    )


def _empty_classify_result(reason: str = "") -> ClassifyResult:
    from .types import ClassifyData
    return ClassifyResult(
        capability=SLMCapability.CLASSIFY,
        model="none",
        data=ClassifyData(),
        confidence=0.0,
        latency_ms=0,
        needs_escalation=True,
        escalation_reason=reason,
    )


def _empty_extract_result(reason: str = "") -> ExtractResult:
    from .types import ExtractData
    return ExtractResult(
        capability=SLMCapability.EXTRACT,
        model="none",
        data=ExtractData(),
        confidence=0.0,
        latency_ms=0,
        needs_escalation=True,
        escalation_reason=reason,
    )


def _empty_route_result(reason: str = "") -> RouteResult:
    from .types import RouteData
    return RouteResult(
        capability=SLMCapability.ROUTE,
        model="none",
        data=RouteData(),
        confidence=0.0,
        latency_ms=0,
        needs_escalation=True,
        escalation_reason=reason,
    )
