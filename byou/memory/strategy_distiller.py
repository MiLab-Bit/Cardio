"""Byou Memory — StrategyDistiller.

Learning Loop 的接入层 — 从 Pipeline 结果中蒸馏策略模式。

流程:
1. 收集多次 Pipeline 的执行记录 + 策略 + 结果
2. 按行业/规模/风险分组
3. 提取共同的成功因素
4. 生成 StrategyPattern (可复用的策略模板)
5. 存入 StrategyMemory + VectorStore
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from byou.memory.types import (
    StrategyMemory, StrategyPattern, StrategyCondition,
    MemoryTier,
)
from byou.memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class StrategyDistiller:
    """策略模式蒸馏器。

    从多个 Pipeline 的 BD 策略中提取成功模式。

    Usage:
        distiller = StrategyDistiller(vector_store)
        pattern = distiller.distill_from_pipeline_memories(strategy_memories)
    """

    def __init__(self, vector_store: VectorStore):
        self._vs = vector_store
        self._patterns: list[StrategyPattern] = []

    # ── 主入口 ────────────────────────────────────

    def distill_from_pipeline(
        self,
        strategy_json: dict[str, Any],
        company_context: dict[str, Any],
        outcome: str,
        pipeline_id: str = "",
    ) -> StrategyMemory:
        """单次 Pipeline 策略 → StrategyMemory。

        Called by: Learning Loop → after pipeline complete
        """
        memory = StrategyMemory(
            company_context=company_context,
            strategy_json=strategy_json,
            outcome=outcome,
            pipeline_id=pipeline_id,
            industry=company_context.get("industry", ""),
            company_scale=company_context.get("employee_count_range", ""),
            risk_level=self._risk_to_level(float(company_context.get("risk_score", 0))),
        )

        # 存入 VectorStore
        self._vs.add(memory.to_memory_entry())

        return memory

    def distill_from_memories(
        self, memories: list[StrategyMemory],
    ) -> list[StrategyPattern]:
        """从多条 StrategyMemory 中提取策略模式。

        Called by: 定时任务 or 手动触发
        """
        if len(memories) < 3:
            logger.info("Not enough memories to distill patterns (%d)", len(memories))
            return []

        patterns: list[StrategyPattern] = []

        # 按 industry 分组
        by_industry: dict[str, list[StrategyMemory]] = defaultdict(list)
        for mem in memories:
            by_industry[mem.industry or "unknown"].append(mem)

        for industry, mems in by_industry.items():
            if len(mems) < 2:
                continue

            # 只取成功的
            won = [m for m in mems if m.outcome == "won"]
            if not won:
                continue

            # 提取共同因素
            common_factors = self._extract_common_factors(won)
            conditions = self._build_conditions(won)

            # 生成模板
            template = self._build_template(won)

            # 创建 pattern
            scales = list(set(m.company_scale for m in won if m.company_scale))
            pattern = StrategyPattern(
                name=f"{industry}_success_pattern",
                description=f"成功策略模式 — 行业: {industry}",
                conditions=conditions,
                template=template,
                applicable_industries=[industry],
                applicable_scales=scales,
                success_count=len(won),
                total_count=len(mems),
                avg_effectiveness=sum(m.effectiveness_score for m in won) / len(won),
                insights=common_factors,
            )
            patterns.append(pattern)

        self._patterns.extend(patterns)
        logger.info("Distilled %d strategy patterns from %d memories", len(patterns), len(memories))
        return patterns

    # ── 查找已有模式 ───────────────────────────────

    def find_patterns(
        self, industry: str = "", scale: str = "", min_success_rate: float = 0.5,
    ) -> list[StrategyPattern]:
        """查找匹配的策略模式"""
        results = []
        for p in self._patterns:
            if industry and industry not in p.applicable_industries:
                continue
            if scale and p.applicable_scales and scale not in p.applicable_scales:
                continue
            if p.success_rate < min_success_rate:
                continue
            results.append(p)
        return sorted(results, key=lambda p: p.success_rate, reverse=True)

    # ── 内部 ──────────────────────────────────────

    @staticmethod
    def _extract_common_factors(memories: list[StrategyMemory]) -> list[str]:
        """提取共同成功因素"""
        all_factors = []
        for mem in memories:
            all_factors.extend(mem.key_factors)
        # 计数并返回出现 >=2 次的
        counter: dict[str, int] = defaultdict(int)
        for f in all_factors:
            counter[f] += 1
        return [f for f, count in counter.items() if count >= 2]

    @staticmethod
    def _build_conditions(memories: list[StrategyMemory]) -> list[StrategyCondition]:
        """构建策略适用条件"""
        conditions: list[StrategyCondition] = []
        industries = list(set(m.industry for m in memories if m.industry))
        if industries:
            conditions.append(StrategyCondition(
                field="industry", operator="contains", value=industries[0], weight=0.5,
            ))
        risk_levels = list(set(m.risk_level for m in memories if m.risk_level))
        if risk_levels:
            conditions.append(StrategyCondition(
                field="risk_level", operator="equals", value=risk_levels[0], weight=0.3,
            ))
        return conditions

    @staticmethod
    def _build_template(memories: list[StrategyMemory]) -> str:
        """用成功案例的策略合成话术模板"""
        templates = []
        for mem in memories[:3]:
            strategy = mem.strategy_json
            approach = strategy.get("approach", "") or strategy.get("bd_approach", "")
            if approach:
                templates.append(approach)
        if not templates:
            return "根据行业特征和客户规模定制 BD 策略"
        return "\n".join(templates)

    @staticmethod
    def _risk_to_level(risk_score: float) -> str:
        if risk_score < 0.2:
            return "low"
        elif risk_score < 0.5:
            return "medium"
        elif risk_score < 0.8:
            return "high"
        return "critical"
