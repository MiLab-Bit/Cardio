"""Byou — Memory & Knowledge Graph Subsystem.

记忆图谱与知识蒸馏层，让每次 Pipeline 不是从零开始。

分层架构 (受 Letta + Mem0 + GraphRAG 启发):

第 1 层: Working Memory     — Pipeline 上下文，生命周期=单次 Pipeline
第 2 层: Session Memory      — 会话内积累，生命周期=单次会话
第 3 层: Long-Term Memory    — 向量存储，已研究的企业语义档案
第 4 层: Knowledge Graph     — 公司/人物/行业/事件关系图谱
第 5 层: Strategy Memory      — Learning Loop 蒸馏出的策略模式

核心组件:
- MemoryManager          — 五层记忆统一门面
- VectorStore            — ChromaDB 向量存储 (Phase 1)
- GraphStore             — NetworkX 图存储 (Phase 2)
- DistillationEngine     — Pipeline 产出 → 记忆入库 (Phase 1-3)
- CaseMatcher            — 相似历史案例匹配 (Phase 1)
- ForgettingPolicy       — 智能遗忘策略 (Phase 3)
- StrategyDistiller      — 策略模式蒸馏 (Phase 3)
"""

from byou.memory.types import (
    # Memory tiers & entries
    MemoryTier, MemoryEntry, MemoryQuery, MemoryQueryResult,
    WorkingMemory, SessionMemory, LongTermMemory,

    # Knowledge Graph
    GraphNode, GraphEdge, NodeType, EdgeType,
    CompanyNode, PersonNode, IndustryNode, ProductNode,
    EventNode, BDContactNode, InsightNode,
    EmploysEdge, CompetesWithEdge, SuppliesToEdge,
    InvestsInEdge, ParticipatedInEdge, LocatedInEdge,
    BelongsToIndustryEdge, HasContactEdge, SimilarToEdge,
    DerivedFromEdge,

    # Case matching
    SimilarCase, CaseQuery, CaseQueryResult, CompanyVector,

    # Strategy memory
    StrategyPattern, StrategyCondition, StrategyMemory,
)

from byou.memory.vector_store import VectorStore
from byou.memory.graph_store import GraphStore
from byou.memory.distillation import DistillationEngine
from byou.memory.case_matcher import CaseMatcher
from byou.memory.forgetting import ForgettingPolicy
from byou.memory.strategy_distiller import StrategyDistiller
from byou.memory.manager import MemoryManager

__all__ = [
    # Types
    "MemoryTier", "MemoryEntry", "MemoryQuery", "MemoryQueryResult",
    "WorkingMemory", "SessionMemory", "LongTermMemory",
    "GraphNode", "GraphEdge", "NodeType", "EdgeType",
    "CompanyNode", "PersonNode", "IndustryNode", "ProductNode",
    "EventNode", "BDContactNode", "InsightNode",
    "EmploysEdge", "CompetesWithEdge", "SuppliesToEdge",
    "InvestsInEdge", "ParticipatedInEdge", "LocatedInEdge",
    "BelongsToIndustryEdge", "HasContactEdge", "SimilarToEdge",
    "DerivedFromEdge",
    "SimilarCase", "CaseQuery", "CaseQueryResult", "CompanyVector",
    "StrategyPattern", "StrategyCondition", "StrategyMemory",
    # Engines
    "VectorStore", "GraphStore", "DistillationEngine",
    "CaseMatcher", "ForgettingPolicy", "StrategyDistiller",
    "MemoryManager",
]
