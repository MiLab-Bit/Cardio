"""Byou Memory — MemoryManager (统一门面).

五层记忆的单一入口，所有 Agent 通过它访问记忆系统。

层级:
1. WorkingMemory   ↔ Agent Pipeline 上下文 (自动创建/销毁)
2. SessionMemory    ↔ 当前会话共享 (跨 Pipeline)
3. VectorStore      ↔ 企业档案语义检索
4. GraphStore       ↔ 实体关系图谱
5. StrategyDistiller ↔ 策略模式蒸馏

Agent 接口:
- ResearcherAgent   → history() + remember()
- StrategistAgent   → find_similar_cases() + lookup_patterns()
- ExtractorAgent    → remember_contact()
- SynthesizerAgent  → get_enrichment_history()
- CriticAgent       → get_graph_quality_report()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from byou.memory.types import (
    MemoryTier, MemoryQuery, MemoryQueryResult,
    WorkingMemory, SessionMemory, LongTermMemory,
    CaseQuery, CaseQueryResult, SimilarCase,
    StrategyMemory, StrategyPattern,
)
from byou.memory.vector_store import VectorStore
from byou.memory.graph_store import GraphStore
from byou.memory.distillation import DistillationEngine
from byou.memory.case_matcher import CaseMatcher
from byou.memory.forgetting import ForgettingPolicy
from byou.memory.strategy_distiller import StrategyDistiller

logger = logging.getLogger(__name__)


class MemoryManager:
    """五层记忆统一门面。

    Usage:
        mm = MemoryManager(persist_path="./byou_memory")
        mm.start_pipeline("company", "person")
        ...
        mm.distill_pipeline_result(research_bundle, pipeline_id)
        mm.end_pipeline()
    """

    def __init__(self, persist_path: str = "./byou_memory_db"):
        self._vector_store = VectorStore(persist_path=persist_path)
        self._graph_store = GraphStore()
        self._distillation = DistillationEngine(self._vector_store, self._graph_store)
        self._case_matcher = CaseMatcher(self._vector_store, self._graph_store)
        self._forgetting = ForgettingPolicy()
        self._strategy_distiller = StrategyDistiller(self._vector_store)

        # 短期记忆
        self._working: WorkingMemory | None = None
        self._session = SessionMemory()

        # 统计
        self._pipeline_count: int = 0
        self._started_at = datetime.now(timezone.utc)

    # ════════════════════════════════════════════════
    # Pipeline 生命周期
    # ════════════════════════════════════════════════

    def start_pipeline(self, company: str = "", person: str = ""):
        """Pipeline 开始 → 创建 WorkingMemory"""
        self._working = WorkingMemory(
            company_name=company,
            person_name=person,
        )
        self._session.recent_pipelines.append(self._working.pipeline_id)
        if company and company not in self._session.recent_companies:
            self._session.recent_companies.append(company)

    def get_working(self) -> WorkingMemory | None:
        """获取当前 WorkingMemory"""
        return self._working

    def update_working(self, **kwargs):
        """更新 WorkingMemory"""
        if self._working:
            for key, value in kwargs.items():
                if hasattr(self._working, key):
                    setattr(self._working, key, value)

    def end_pipeline(self):
        """Pipeline 结束"""
        if self._working:
            self._working.notes.append(
                f"Pipeline ended at {datetime.now(timezone.utc).isoformat()}"
            )
        self._pipeline_count += 1
        self._working = None

    # ════════════════════════════════════════════════
    # 历史查询 (ResearcherAgent)
    # ════════════════════════════════════════════════

    def history(self, company_name: str, top_k: int = 5) -> list[LongTermMemory]:
        """查询历史上是否研究过该公司"""
        from byou.memory.types import MemoryTier

        result = self._vector_store.search(MemoryQuery(
            query_text=company_name,
            tier=MemoryTier.LONG_TERM,
            top_k=top_k,
        ))

        profiles: list[LongTermMemory] = []
        for entry in result.entries:
            content = entry.content
            if isinstance(content, dict):
                try:
                    profiles.append(LongTermMemory(**content))
                except Exception:
                    pass
        return profiles

    def remember(self, research_bundle: dict[str, Any]) -> dict[str, Any]:
        """记住一次研究结果 → Graph + Vector"""
        from datetime import datetime, timezone

        pipeline_id = self._working.pipeline_id if self._working else ""
        stats = self._distillation.distill(research_bundle, pipeline_id=pipeline_id)

        # 同时记录到 session
        company = research_bundle.get("company_name", "")
        risk = research_bundle.get("risk", {}) or {}
        risk_score = risk.get("risk_score", 0)
        self._session.discoveries.append({
            "company": company,
            "risk_score": risk_score,
            "at": datetime.now(timezone.utc).isoformat(),
            "pipeline_id": pipeline_id,
        })

        return stats

    # ════════════════════════════════════════════════
    # 相似案例 (StrategistAgent)
    # ════════════════════════════════════════════════

    def find_similar_cases(self, query: CaseQuery) -> CaseQueryResult:
        """查找最相似的历史案例"""
        return self._case_matcher.match(query)

    def lookup_patterns(
        self, industry: str = "", scale: str = "",
    ) -> list[StrategyPattern]:
        """查找历史上成功的策略模式"""
        return self._strategy_distiller.find_patterns(
            industry=industry, scale=scale,
        )

    # ════════════════════════════════════════════════
    # 策略蒸馏 (Learning Loop)
    # ════════════════════════════════════════════════

    def distill_strategy(
        self, strategy_json: dict, company_context: dict, outcome: str,
    ) -> StrategyMemory:
        """记录一次策略执行结果"""
        pipeline_id = self._working.pipeline_id if self._working else ""
        return self._strategy_distiller.distill_from_pipeline(
            strategy_json=strategy_json,
            company_context=company_context,
            outcome=outcome,
            pipeline_id=pipeline_id,
        )

    def extract_global_patterns(self) -> list[StrategyPattern]:
        """从所有记录的策略中全局蒸馏"""
        from byou.memory.types import MemoryTier

        result = self._vector_store.search(MemoryQuery(
            query_text="strategy",
            tier=MemoryTier.STRATEGY,
            top_k=200,
        ))

        memories: list[StrategyMemory] = []
        for entry in result.entries:
            content = entry.content
            if isinstance(content, dict):
                try:
                    memories.append(StrategyMemory(**content))
                except Exception:
                    pass

        return self._strategy_distiller.distill_from_memories(memories)

    # ════════════════════════════════════════════════
    # 图谱查询 (SynthesizerAgent / CriticAgent)
    # ════════════════════════════════════════════════

    def get_neighbors(self, company_name: str, max_depth: int = 1):
        """公司的邻居网络"""
        from byou.memory.types import NodeType

        nodes = self._graph_store.find_nodes(name=company_name, node_type=NodeType.COMPANY)
        if not nodes:
            return {}
        return self._graph_store.get_neighbors(nodes[0].id, max_depth=max_depth)

    def get_competitors(self, company_name: str):
        """竞争对手"""
        from byou.memory.types import NodeType

        nodes = self._graph_store.find_nodes(name=company_name, node_type=NodeType.COMPANY)
        if not nodes:
            return []
        return self._graph_store.get_competitors(nodes[0].id)

    def get_equity_tree(self, company_name: str):
        """股权穿透"""
        from byou.memory.types import NodeType

        nodes = self._graph_store.find_nodes(name=company_name, node_type=NodeType.COMPANY)
        if not nodes:
            return {}
        return self._graph_store.get_equity_tree(nodes[0].id)

    def graph_stats(self) -> dict:
        """图谱统计"""
        return self._graph_store.stats()

    # ════════════════════════════════════════════════
    # 维护
    # ════════════════════════════════════════════════

    def run_maintenance(self):
        """运行记忆维护 (遗忘 + 压缩 + 统计)"""
        stat = self._graph_store.stats()

        # 简单容量检查
        if self._vector_store.count(tier=MemoryTier.LONG_TERM) > self._forgetting.max_long_term:
            logger.warning("Long-term memory pool at capacity, consider cleanup")

        return {
            "graph": stat,
            "vector_long_term": self._vector_store.count(tier=MemoryTier.LONG_TERM),
            "vector_strategy": self._vector_store.count(tier=MemoryTier.STRATEGY),
            "session_companies": len(self._session.recent_companies),
            "pipeline_count": self._pipeline_count,
        }

    @property
    def stats(self) -> dict:
        return self.run_maintenance()

    @property
    def is_ready(self) -> bool:
        return self._vector_store is not None
