"""Byou Memory — CaseMatcher.

历史企业案例的语义相似匹配。

匹配维度 (加权):
- 行业相同 (0.30)  → 字符串匹配
- 规模相近 (0.20)  → employee_range 转换为数值再比较
- 风险画像 (0.15)  → risk_score 欧氏距离
- 语义向量 (0.35)  → 向量余弦相似度

用于: StrategistAgent 在生成 BD 策略前查询历史参考。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from byou.memory.types import (
    SimilarCase, CaseQuery, CaseQueryResult,
    LongTermMemory, StrategyMemory,
)
from byou.memory.vector_store import VectorStore
from byou.memory.graph_store import GraphStore

logger = logging.getLogger(__name__)

# 员工规模 → 数值 (用于距离计算)
_EMPLOYEE_SCALE_MAP: dict[str, float] = {
    "1-10": 5, "10-50": 30, "50-100": 75, "100-500": 300,
    "500-1000": 750, "1000-5000": 3000, "5000-10000": 7500,
    "10000+": 15000,
}

# 营收范围 → 数值
_REVENUE_SCALE_MAP: dict[str, float] = {
    "100万以下": 50, "100万-500万": 300, "500万-1000万": 750,
    "1000万-5000万": 3000, "5000万-1亿": 7500, "1亿-5亿": 30000,
    "5亿-10亿": 75000, "10亿以上": 150000,
}


class CaseMatcher:
    """历史相似案例匹配器。

    Usage:
        matcher = CaseMatcher(vector_store, graph_store)
        result = matcher.match(CaseQuery(
            company_name="某科技", company_profile={...}
        ))
        for case in result.cases:
            print(case.company_name, case.similarity_score)
    """

    def __init__(
        self,
        vector_store: VectorStore,
        graph_store: GraphStore | None = None,
    ):
        self._vs = vector_store
        self._gs = graph_store
        self._strategy_cache: dict[str, StrategyMemory | None] = {}

    def match(self, query: CaseQuery) -> CaseQueryResult:
        """匹配最相似的历史案例"""
        t0 = time.monotonic()

        # Step 1: 向量检索 → 语义相似候选
        from byou.memory.types import MemoryQuery, MemoryTier

        mem_query = MemoryQuery(
            query_text=query.company_name,
            tier=MemoryTier.LONG_TERM,
            top_k=query.top_k * 3,  # 多取一些候选做精细排序
        )
        vector_results = self._vs.search(mem_query)

        # Step 2: 精细排序 (行业 + 规模 + 风险 + 向量)
        cases = self._fine_rank(vector_results, query)

        # Step 3: 策略回填
        if query.include_strategies:
            for case in cases:
                if case.profile:
                    case.strategy = self._lookup_strategy(case.profile.company_name)

        query_time_ms = (time.monotonic() - t0) * 1000

        return CaseQueryResult(
            query=query,
            cases=cases[:query.top_k],
            query_time_ms=round(query_time_ms, 2),
            total_candidates_searched=len(vector_results.entries),
        )

    # ── 精细排序 ──────────────────────────────────

    def _fine_rank(
        self,
        vector_results: "MemoryQueryResult",
        query: CaseQuery,
    ) -> list[SimilarCase]:
        """多维加权排序"""
        ranked: list[SimilarCase] = []

        query_profile = query.company_profile
        query_industry = query_profile.get("industry", "")
        query_emp = query_profile.get("employee_count_range", "")
        query_risk = float(query_profile.get("risk_score", 0))

        for i, entry in enumerate(vector_results.entries):
            content = entry.content
            if not content:
                continue

            # 重建 LongTermMemory
            ltm = LongTermMemory(**content) if isinstance(content, dict) else None
            if not ltm:
                continue

            # 计算各维度分数
            industry_score = self._industry_match(query_industry, ltm.industry)
            scale_score = self._scale_match(query_emp, ltm.employee_range)
            risk_score = 1.0 - min(abs(query_risk - ltm.risk_score), 1.0)
            vector_score = vector_results.scores[i] if i < len(vector_results.scores) else 0.0

            # 加权
            total = (
                industry_score * query.industry_weight
                + scale_score * query.scale_weight
                + risk_score * query.risk_weight
                + vector_score * query.semantic_weight
            )

            if total < query.min_similarity:
                continue

            # 产生匹配原因
            reasons = []
            if industry_score > 0.8:
                reasons.append(f"同行: {ltm.industry}")
            if scale_score > 0.7:
                reasons.append(f"规模相近: {ltm.employee_range}")
            if risk_score > 0.8:
                reasons.append(f"风险相似: {ltm.risk_score}")
            if vector_score > 0.7:
                reasons.append("语义高度相似")

            ranked.append(SimilarCase(
                rank=0,
                company_name=ltm.company_name,
                similarity_score=round(total, 4),
                match_reasons=reasons,
                profile=ltm,
            ))

        # 排序
        ranked.sort(key=lambda c: c.similarity_score, reverse=True)
        for i, case in enumerate(ranked):
            case.rank = i + 1

        return ranked

    # ── 维度匹配 ──────────────────────────────────

    @staticmethod
    def _industry_match(q_industry: str, c_industry: str) -> float:
        """行业匹配"""
        if not q_industry or not c_industry:
            return 0.3  # 中性
        if q_industry == c_industry:
            return 1.0
        # 包含关系
        if q_industry in c_industry or c_industry in q_industry:
            return 0.7
        return 0.0

    @staticmethod
    def _scale_match(q_range: str, c_range: str) -> float:
        """规模匹配 (基于数值映射)"""
        q_val = _EMPLOYEE_SCALE_MAP.get(q_range, 0)
        c_val = _EMPLOYEE_SCALE_MAP.get(c_range, 0)
        if q_val == 0 and c_val == 0:
            return 0.5  # 都未知 → 中性
        if q_val == 0 or c_val == 0:
            return 0.2
        # 对数化的相对距离
        import math
        ratio = abs(math.log10(q_val + 1) - math.log10(c_val + 1))
        return max(0.0, 1.0 - ratio / 3.0)

    # ── 策略查詢 ──────────────────────────────────

    def _lookup_strategy(self, company_name: str) -> StrategyMemory | None:
        """查找历史上对该公司的策略"""
        if company_name in self._strategy_cache:
            return self._strategy_cache[company_name]

        from byou.memory.types import MemoryQuery, MemoryTier

        result = self._vs.search(MemoryQuery(
            query_text=company_name,
            tier=MemoryTier.STRATEGY,
            top_k=1,
        ))
        if result.entries:
            content = result.entries[0].content
            if isinstance(content, dict):
                try:
                    strat = StrategyMemory(**content)
                    self._strategy_cache[company_name] = strat
                    return strat
                except Exception:
                    pass

        self._strategy_cache[company_name] = None
        return None
