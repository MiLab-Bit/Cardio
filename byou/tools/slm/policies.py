"""SLM Policies — 何时用 SLM vs LLM 的决策策略。

核心决策树:
1. 输入是否适合 SLM？ (稳定结构? 固定标签？)
2. SLM 是否有对应能力？
3. SLM 执行 → confidence >= min_confidence？
4. 如果否 → escalation → LLM

渐进式置信度阈值 — 越关键的任务，阈值越高。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .types import EscalationConfig, SLMCapability

logger = logging.getLogger(__name__)

# ── 按任务类别的默认阈值 ──────────────────────────────────────

# (capability, context_tag) → EscalationConfig
_DEFAULT_POLICIES: dict[tuple[str, str], EscalationConfig] = {
    # Browser 搜索结果 rerank — 高频、错了好修
    ("rerank", "browser_snippet"): EscalationConfig(
        min_confidence=0.5,
        max_latency_ms=300,
    ),
    # Research intent 分类 — 中等重要
    ("classify", "research_intent"): EscalationConfig(
        min_confidence=0.6,
        max_latency_ms=200,
    ),
    # Enrichment 字段抽取 — 需要准确
    ("extract", "company_fields"): EscalationConfig(
        min_confidence=0.65,
        max_latency_ms=500,
    ),
    # Memory 相似案例匹配
    ("match", "memory_case"): EscalationConfig(
        min_confidence=0.55,
        max_latency_ms=300,
    ),
    # Customer level 分类 (A/B/C/D) — 中等
    ("classify", "customer_level"): EscalationConfig(
        min_confidence=0.6,
        max_latency_ms=200,
    ),
    # Critic 前置筛查 — 边界宽容
    ("classify", "critic_prescreen"): EscalationConfig(
        min_confidence=0.5,
        max_latency_ms=300,
    ),
    # 默认策略
    ("default", "default"): EscalationConfig(
        min_confidence=0.6,
        max_latency_ms=500,
    ),
}


@dataclass
class PolicyDecision:
    """策略决策结果"""
    should_use_slm: bool
    capability: SLMCapability | None = None
    config: EscalationConfig | None = None
    reason: str = ""


class SLMPolicies:
    """小模型使用策略引擎"""

    def __init__(self):
        self._policies: dict[str, EscalationConfig] = {}
        # 加载默认策略
        for (cap, ctx), config in _DEFAULT_POLICIES.items():
            key = self._make_key(cap, ctx)
            self._policies[key] = config

    @staticmethod
    def _make_key(capability: str, context_tag: str) -> str:
        return f"{capability}::{context_tag}"

    # ── 决策 ───────────────────────────────────────────────

    def should_use_slm(
        self,
        capability: SLMCapability,
        context_tag: str = "default",
        input_is_structured: bool = True,
        output_has_fixed_labels: bool = False,
        is_high_frequency: bool = True,
        has_fallback: bool = True,
    ) -> PolicyDecision:
        """判断是否应该使用 SLM。

        五条决策原则:
        1. 输入结构相对稳定 → +1
        2. 输出类别有限或格式固定 → +1
        3. 可以定义明确标签/评分标准 → +1
        4. 高频调用 → +1
        5. 错了可以 fallback 到大模型 → +1

        得分 >= 3 → 使用 SLM
        """
        score = 0
        reasons: list[str] = []

        if input_is_structured:
            score += 1
            reasons.append("structured_input")
        if output_has_fixed_labels:
            score += 1
            reasons.append("fixed_labels")
        if has_fallback:
            score += 1
            reasons.append("has_fallback")
        if is_high_frequency:
            score += 2                  # 高频任务权重翻倍
            reasons.append("high_frequency")

        should_use = score >= 3
        config = None

        if should_use:
            key = self._make_key(capability.value, context_tag)
            config = self._policies.get(key) or self._policies.get("default::default")

        reason_str = f"score={score}/5 ({', '.join(reasons)})"

        if not should_use:
            reason_str += " → escalate to LLM"

        return PolicyDecision(
            should_use_slm=should_use,
            capability=capability if should_use else None,
            config=config,
            reason=reason_str,
        )

    def get_config(
        self, capability: SLMCapability, context_tag: str = "default"
    ) -> EscalationConfig:
        """获取指定 capability + context 的升级配置"""
        key = self._make_key(capability.value, context_tag)
        return self._policies.get(key) or EscalationConfig()

    def set_config(
        self, capability: SLMCapability, context_tag: str, config: EscalationConfig,
    ) -> None:
        """设置/覆盖配置"""
        key = self._make_key(capability.value, context_tag)
        self._policies[key] = config

    def needs_escalation(self, confidence: float, config: EscalationConfig | None = None) -> bool:
        """判断 SLM 结果是否需要升级到 LLM"""
        cfg = config or EscalationConfig()
        return confidence < cfg.min_confidence

    def list_policies(self) -> dict[str, EscalationConfig]:
        return dict(self._policies)


# ── Quick helpers ──────────────────────────────────────────────

def quick_decision(
    capability: SLMCapability,
    context_tag: str = "default",
    **kwargs: Any,
) -> PolicyDecision:
    """快速决策快捷方法"""
    policies = SLMPolicies()
    return policies.should_use_slm(capability, context_tag, **kwargs)
