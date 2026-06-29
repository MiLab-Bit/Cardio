"""SLM Registry — 模型注册、加载与查找。

设计原则:
- Agent 声明 SLMCapability，不绑定具体模型名
- Registry 负责根据 capability 找到最佳可用模型
- 支持降级链: preferred → fallback → heuristic
"""

from __future__ import annotations

import logging
from typing import Any

from .types import SLMCapability

# Detect sklearn availability
try:
    import sklearn  # noqa: F401
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

logger = logging.getLogger(__name__)


class ModelInfo:
    """单个已注册的模型信息"""

    def __init__(
        self,
        model_id: str,
        capability: SLMCapability,
        provider: str = "local",
        priority: int = 0,
        model_path: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        self.model_id = model_id
        self.capability = capability
        self.provider = provider
        self.priority = priority           # 越大越优先
        self.model_path = model_path
        self.metadata = metadata or {}
        self.is_loaded = False
        self._model_instance: Any = None


class SLMRegistry:
    """小模型注册中心"""

    def __init__(self):
        self._models: dict[str, ModelInfo] = {}
        self._by_capability: dict[SLMCapability, list[ModelInfo]] = {
            c: [] for c in SLMCapability
        }

    # ── Register ───────────────────────────────────────────────

    def register(
        self,
        model_id: str,
        capability: SLMCapability,
        provider: str = "local",
        priority: int = 0,
        model_path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ModelInfo:
        """注册一个模型"""
        if model_id in self._models:
            logger.warning("Model %s already registered, overwriting", model_id)

        info = ModelInfo(
            model_id=model_id,
            capability=capability,
            provider=provider,
            priority=priority,
            model_path=model_path,
            metadata=metadata,
        )
        self._models[model_id] = info
        self._by_capability[capability].append(info)

        # 按 priority 降序排列
        self._by_capability[capability].sort(key=lambda m: -m.priority)

        logger.info("Registered SLM: %s → %s (priority=%d)", model_id, capability.value, priority)
        return info

    def register_many(self, entries: list[dict[str, Any]]) -> list[ModelInfo]:
        """批量注册"""
        result = []
        for entry in entries:
            info = self.register(
                model_id=entry["model_id"],
                capability=SLMCapability(entry["capability"]),
                provider=entry.get("provider", "local"),
                priority=entry.get("priority", 0),
                model_path=entry.get("model_path", ""),
                metadata=entry.get("metadata"),
            )
            result.append(info)
        return result

    # ── Lookup ─────────────────────────────────────────────────

    def get_best(self, capability: SLMCapability) -> ModelInfo | None:
        """获取某个 capability 的最高优先级模型"""
        candidates = self._by_capability.get(capability, [])
        return candidates[0] if candidates else None

    def get_candidates(self, capability: SLMCapability) -> list[ModelInfo]:
        """获取某个 capability 的所有候选模型（按优先级降序）"""
        return list(self._by_capability.get(capability, []))

    def get_model(self, model_id: str) -> ModelInfo | None:
        """按 ID 查找"""
        return self._models.get(model_id)

    def has_capability(self, capability: SLMCapability) -> bool:
        """是否有对应的模型"""
        return len(self._by_capability.get(capability, [])) > 0

    # ── Capabilities ───────────────────────────────────────────

    def list_capabilities(self) -> list[SLMCapability]:
        """列出所有已注册的能力"""
        return [c for c, models in self._by_capability.items() if models]

    def list_models(self) -> list[dict[str, Any]]:
        """列出所有已注册的模型"""
        return [
            {
                "model_id": m.model_id,
                "capability": m.capability.value,
                "provider": m.provider,
                "priority": m.priority,
                "is_loaded": m.is_loaded,
            }
            for m in self._models.values()
        ]

    # ── Defaults ───────────────────────────────────────────────

    def register_defaults(self) -> None:
        """注册默认模型：真实模型优先，heuristic fallback 降级"""
        # ── 真实模型（高优先级 100）──
        # 在运行时如果环境满足就会覆盖注册
        from .real_engines import model_available
        if model_available():
            self.register(
                model_id="qwen25_classifier",
                capability=SLMCapability.CLASSIFY,
                provider="real",
                priority=100,
                metadata={"description": "Qwen2.5-0.5B classification"},
            )
            self.register(
                model_id="qwen25_router",
                capability=SLMCapability.ROUTE,
                provider="real",
                priority=100,
                metadata={"description": "Qwen2.5-0.5B routing"},
            )
            self.register(
                model_id="qwen25_extractor",
                capability=SLMCapability.EXTRACT,
                provider="real",
                priority=100,
                metadata={"description": "Qwen2.5-0.5B extraction"},
            )
            self.register(
                model_id="qwen25_compressor",
                capability=SLMCapability.COMPRESS,
                provider="real",
                priority=100,
                metadata={"description": "Qwen2.5-0.5B compression"},
            )

        # ── TF-IDF 重排器（中优先级 50）──
        if _HAS_SKLEARN:
            self.register(
                model_id="tfidf_reranker",
                capability=SLMCapability.RERANK,
                provider="real",
                priority=50,
                metadata={"description": "TF-IDF cosine similarity reranking"},
            )

        # ── Heuristic fallbacks（最低优先级 -100）──
        self.register(
            model_id="heuristic_reranker",
            capability=SLMCapability.RERANK,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Keyword+rule based reranking fallback"},
        )
        self.register(
            model_id="heuristic_classifier",
            capability=SLMCapability.CLASSIFY,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Keyword+rule based classification fallback"},
        )
        self.register(
            model_id="heuristic_extractor",
            capability=SLMCapability.EXTRACT,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Regex+pattern based extraction fallback"},
        )
        self.register(
            model_id="heuristic_compressor",
            capability=SLMCapability.COMPRESS,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Rule-based text compression fallback"},
        )
        self.register(
            model_id="heuristic_router",
            capability=SLMCapability.ROUTE,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Keyword-based intent routing fallback"},
        )
        self.register(
            model_id="heuristic_matcher",
            capability=SLMCapability.MATCH,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Jaccard/ngram similarity matching fallback"},
        )
        self.register(
            model_id="heuristic_scorer",
            capability=SLMCapability.SCORE,
            provider="heuristic",
            priority=-100,
            metadata={"description": "Rule-based scoring fallback"},
        )


# ── Singleton ──────────────────────────────────────────────────

_default_registry: SLMRegistry | None = None


def get_registry() -> SLMRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = SLMRegistry()
        _default_registry.register_defaults()
    return _default_registry
