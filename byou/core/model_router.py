# byou/core/model_router.py
"""小模型路由架构 — 三层推理 + 智能分层。

Implements the "三层推理架构" from the roadmap:
  - High-Freq / Low-Cost Tier:   fast SLM for simple tasks
  - Medium Reasoning Tier:        balanced model for most tasks
  - Deep Reasoning Tier:         powerful model for complex tasks

Routing strategy:
  1. Classify task complexity (prompt length, keywords, intent)
  2. Route to appropriate tier
  3. Escalate if confidence < threshold (cascade)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from byou.config import get_settings

logger = logging.getLogger(__name__)

# ── Rust 加速兼容层 ──────────────────────────────────────────────────────────────
# 尝试导入 Rust 实现的 ComplexityClassifier；失败时自动降级到纯 Python。

try:
    from byou._rust_compat import ComplexityClassifier as _RustComplexityClassifier

    _HAS_RUST_CLASSIFIER = True
except ImportError:
    _RustComplexityClassifier = None
    _HAS_RUST_CLASSIFIER = False
    logger.info("Rust ComplexityClassifier not available, using pure Python.")


# ════════════════════════════════════════════════════════
# ModelTier
# ════════════════════════════════════════════════════════

class ModelTier(Enum):
    CHEAP = "cheap"    # fast, cheap: Phi-3, Gemma, GPT-3.5
    MEDIUM = "medium"  # balanced: GPT-4o-mini, Claude Haiku
    DEEP = "deep"      # powerful: GPT-4, Claude Sonnet


# ════════════════════════════════════════════════════════
# TaskComplexity
# ════════════════════════════════════════════════════════

@dataclass
class ComplexityScore:
    """Task complexity score with breakdown."""

    overall: float = 0.0       # 0.0 = simple, 1.0 = complex
    prompt_length: float = 0.0
    reasoning_depth: float = 0.0
    tool_usage: float = 0.0
    history_length: float = 0.0
    tier_suggestion: ModelTier = ModelTier.MEDIUM
    reasons: list[str] = field(default_factory=list)


class TaskComplexityClassifier:
    """Classify task complexity to determine model tier.

    Uses heuristic rules (no ML, fast):
      - Prompt length: < 200 tokens → cheap, > 2000 → deep
      - Keywords: "分析/推理/对比/方案" → medium+, "简单/提取/清洗" → cheap
      - Tool usage: > 3 tools → medium+
      - History: > 10 turns → medium+
    """

    # Keywords that suggest cheap tasks.
    # We store them as plain strings but match them as word-boundary
    # substrings so "不提取" / "提取客户" both score correctly.
    # A negated prefix ("不提取", "无需分析") cancels a hit.
    def __init__(self):
        self._use_rust = _HAS_RUST_CLASSIFIER
        if self._use_rust:
            self._rs = _RustComplexityClassifier()
            logger.info('Using Rust-accelerated ComplexityClassifier.')
        else:
            self._rs = None

    
    _CHEAP_KEYWORDS: set[str] = {
        "提取", "清洗", "格式化", "标准化", "分类", "标签",
        "extract", "clean", "format", "classify", "tag",
    }

    # Keywords that suggest deep tasks.
    _DEEP_KEYWORDS: set[str] = {
        "分析", "推理", "对比", "方案", "评估", "策略", "设计",
        "analyze", "reason", "compare", "strategy", "evaluate", "design",
    }

    # Negation prefixes that cancel a keyword hit.
    # e.g. "不分析" → negated; "无需分析" → negated.
    _NEGATION_PREFIXES: tuple[str, ...] = (
        "不", "无", "别", "无需", "不必", "不要", "没", "没有",
        "don\'t", "no ", "not ", "skip ", "without",
    )

    def classify(
        self,
        prompt: str,
        tools: list[str] | None = None,
        history_turns: int = 0,
        force_tier: ModelTier | None = None,
    ) -> ComplexityScore:
        """Classify a task and return the suggested tier."""
        if force_tier:
            return ComplexityScore(
                overall=0.5,
                tier_suggestion=force_tier,
                reasons=["forced"],
            )

        reasons: list[str] = []
        scores: list[float] = []

        # 1. Prompt length
        char_count = len(prompt)
        if char_count < 100:
            length_score = 0.1
            reasons.append(f"short_prompt({char_count}_chars)")
        elif char_count < 500:
            length_score = 0.3
            reasons.append(f"medium_prompt({char_count}_chars)")
        elif char_count < 2000:
            length_score = 0.6
            reasons.append(f"long_prompt({char_count}_chars)")
        else:
            length_score = 0.9
            reasons.append(f"very_long_prompt({char_count}_chars)")
        scores.append(length_score)

        # 2. Keyword analysis with negation handling
        prompt_lower = prompt.lower()

        def _score_keyword(prompt_txt: str, keywords: set[str]) -> int:
            """Count keyword hits, minus negated hits."""
            hits = 0
            for kw in keywords:
                if kw in prompt_txt:
                    # Check if this hit has a negation prefix immediately before it.
                    pos = prompt_txt.find(kw)
                    for neg in self._NEGATION_PREFIXES:
                        prefix_end = pos - len(neg)
                        if prefix_end >= 0 and prompt_txt[prefix_end:pos] == neg:
                            hits -= 1    # negated — cancel
                            break
                    else:
                        hits += 1
            return max(0, hits)

        cheap_hits = _score_keyword(prompt_lower, self._CHEAP_KEYWORDS)
        deep_hits = _score_keyword(prompt_lower, self._DEEP_KEYWORDS)

        if cheap_hits > deep_hits and cheap_hits >= 1:
            keyword_score = 0.2
            reasons.append(f"cheap_keywords(+{cheap_hits})")
        elif deep_hits >= 2:
            keyword_score = 0.8
            reasons.append(f"deep_keywords({deep_hits})")
        elif deep_hits == 1:
            keyword_score = 0.6
            reasons.append(f"partial_deep_keywords(1)")
        else:
            keyword_score = 0.5
            reasons.append("neutral_keywords")
        scores.append(keyword_score)

        # 3. Tool usage
        tool_count = len(tools) if tools else 0
        if tool_count == 0:
            tool_score = 0.2
            reasons.append("no_tools")
        elif tool_count <= 2:
            tool_score = 0.4
            reasons.append(f"few_tools({tool_count})")
        else:
            tool_score = 0.7
            reasons.append(f"many_tools({tool_count})")
        scores.append(tool_score)

        # 4. History length
        if history_turns == 0:
            history_score = 0.2
            reasons.append("no_history")
        elif history_turns <= 5:
            history_score = 0.4
            reasons.append(f"short_history({history_turns})")
        else:
            history_score = 0.7
            reasons.append(f"long_history({history_turns})")
        scores.append(history_score)

        # Overall score
        overall = sum(scores) / len(scores)

        # Map to tier
        if overall < 0.35:
            tier = ModelTier.CHEAP
        elif overall < 0.65:
            tier = ModelTier.MEDIUM
        else:
            tier = ModelTier.DEEP

        return ComplexityScore(
            overall=round(overall, 3),
            prompt_length=round(length_score, 3),
            reasoning_depth=round(keyword_score, 3),
            tool_usage=round(tool_score, 3),
            history_length=round(history_score, 3),
            tier_suggestion=tier,
            reasons=reasons,
        )


# ════════════════════════════════════════════════════════
# ModelRouter
# ════════════════════════════════════════════════════════

@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    tier: ModelTier
    model_name: str
    confidence_threshold: float = 0.7
    escalate_on_low_confidence: bool = True
    max_escalations: int = 2
    reasons: list[str] = field(default_factory=list)


class ModelRouter:
    """Route tasks to appropriate model tier.

    Configuration (from settings or config):
      tiers:
        cheap:
          model: "gpt-3.5-turbo"
          base_url: "https://api.openai.com/v1"
          api_key: "..."
          confidence_threshold: 0.6
        medium:
          model: "gpt-4o-mini"
          base_url: "https://api.openai.com/v1"
          confidence_threshold: 0.75
        deep:
          model: "gpt-4o"
          base_url: "https://api.openai.com/v1"
          confidence_threshold: 0.85

    Usage:
        from byou.core.model_router import ModelRouter, ModelTier
        from byou.core.llm_client import get_client_for_tier

        router = ModelRouter()
        decision = router.route(prompt, tools, history)
        client = get_client_for_tier(decision.tier)
        result = await client.chat.completions.create(
            model=decision.model_name,
            messages=[{"role": "user", "content": prompt}],
        )
        if result.confidence < decision.confidence_threshold:
            decision = router.escalate(decision)
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._settings = get_settings()
        self._config = config or self._load_config_from_settings()
        self._classifier = TaskComplexityClassifier()

    def _load_config_from_settings(self) -> dict[str, Any]:
        """Load tier config from settings (with defaults)."""
        return {
            "tiers": {
                "cheap": {
                    "model": getattr(self._settings, "model_cheap", "gpt-3.5-turbo"),
                    "confidence_threshold": 0.6,
                },
                "medium": {
                    "model": getattr(self._settings, "model_medium", "gpt-4o-mini"),
                    "confidence_threshold": 0.75,
                },
                "deep": {
                    "model": getattr(self._settings, "model_deep", "gpt-4o"),
                    "confidence_threshold": 0.85,
                },
            },
        }

    def route(
        self,
        prompt_or_task: str | ComplexityScore,
        tools: list[str] | None = None,
        history_turns: int = 0,
        force_tier: ModelTier | None = None,
    ) -> RoutingDecision:
        """Route a task to the appropriate model tier.

        Args:
            prompt_or_task: either a plain text prompt (str) or a
                pre-built :class:`TaskComplexity` object.
            tools: list of tool names (used when prompt_or_task is str).
            history_turns: conversation turn count (used when prompt_or_task is str).
            force_tier: override the routing decision.

        Returns:
            RoutingDecision with the selected tier and metadata.
        """
        if isinstance(prompt_or_task, ComplexityScore):
            score = prompt_or_task
        else:
            score = self._classifier.classify(
                prompt=prompt_or_task,
                tools=tools,
                history_turns=history_turns,
                force_tier=force_tier,
            )

        tier = score.tier_suggestion
        tier_config = self._config["tiers"].get(tier.value, {})

        return RoutingDecision(
            tier=tier,
            model_name=tier_config.get("model", self._default_model(tier)),
            confidence_threshold=tier_config.get("confidence_threshold", 0.7),
            escalate_on_low_confidence=True,
            reasons=score.reasons,
        )

    def escalate(self, decision: RoutingDecision) -> RoutingDecision:
        """Escalate a routing decision to the next higher tier."""
        tier_order = [ModelTier.CHEAP, ModelTier.MEDIUM, ModelTier.DEEP]
        current_idx = tier_order.index(decision.tier)

        if current_idx >= len(tier_order) - 1:
            logger.warning("Already at deepest tier, cannot escalate further")
            return decision

        new_tier = tier_order[current_idx + 1]
        tier_config = self._config["tiers"].get(new_tier.value, {})

        logger.info("Escalating: %s → %s", decision.tier.value, new_tier.value)
        return RoutingDecision(
            tier=new_tier,
            model_name=tier_config.get("model", self._default_model(new_tier)),
            confidence_threshold=tier_config.get("confidence_threshold", 0.7),
            escalate_on_low_confidence=decision.escalate_on_low_confidence,
            reasons=decision.reasons + [f"escalated_from_{decision.tier.value}"],
        )

    def get_model_name(self, tier: ModelTier) -> str:
        """Get the model name for a tier."""
        return self._config["tiers"].get(tier.value, {}).get("model", self._default_model(tier))

    def _default_model(self, tier: ModelTier) -> str:
        defaults = {
            ModelTier.CHEAP: "gpt-3.5-turbo",
            ModelTier.MEDIUM: "gpt-4o-mini",
            ModelTier.DEEP: "gpt-4o",
        }
        return defaults[tier]
