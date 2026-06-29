"""Byou Memory — DistillationEngine.

Pipeline 产出 → 记忆入库的蒸馏流水线。

流程 (受 GraphRAG 实体提取 + 关系构建启发):
1. 解析 ResearchBundle → 提取实体 (Company/Person/Industry/Event/Contact/Insight)
2. 提取关系 (EMPLOYS, COMPETES_WITH, BELONGS_TO, etc.)
3. 去重与合并 (查已有节点 → merge or create)
4. 向量索引更新
5. 图索引更新
"""

from __future__ import annotations

import logging
import re
from typing import Any

from byou.memory.types import (
    GraphNode, GraphEdge, NodeType, EdgeType,
    CompanyNode, PersonNode, IndustryNode, EventNode,
    BDContactNode, InsightNode,
    CompetesWithEdge, BelongsToIndustryEdge, HasContactEdge,
    LocatedInEdge, SimilarToEdge, DerivedFromEdge,
    LongTermMemory, MemoryEntry, MemoryTier, DataCategory,
)
from byou.memory.vector_store import VectorStore
from byou.memory.graph_store import GraphStore

logger = logging.getLogger(__name__)


class DistillationEngine:
    """知识蒸馏引擎 — Pipeline 产出自动入库。

    Usage:
        engine = DistillationEngine(vector_store, graph_store)
        await engine.distill(research_bundle, pipeline_id="pipe_001")
    """

    def __init__(self, vector_store: VectorStore, graph_store: GraphStore):
        self._vs = vector_store
        self._gs = graph_store

    # ── 主入口 ────────────────────────────────────

    def distill(
        self,
        research_bundle: dict[str, Any],
        pipeline_id: str = "",
    ) -> dict[str, Any]:
        """蒸馏一次 Pipeline 产物到记忆系统。

        Args:
            research_bundle: ResearcherAgent 产出的 ResearchBundle (dict 形式)
            pipeline_id: 来源 Pipeline ID

        Returns:
            {"entities_created": N, "entities_merged": M, "relations_added": R, "insights": I}
        """
        stats = {
            "entities_created": 0, "entities_merged": 0,
            "relations_added": 0, "insights": 0,
        }

        company_name = research_bundle.get("company_name", "")
        if not company_name:
            return stats

        profile = research_bundle.get("profile", {}) or {}
        risk = research_bundle.get("risk", {}) or {}
        identity = research_bundle.get("identity", {}) or {}

        # ── Step 1: 提取实体 ────────────────────
        entities = self._extract_entities(company_name, profile, risk, identity, research_bundle)
        for entity in entities:
            if isinstance(entity, GraphNode):
                rid = self._gs.add_node(entity)
                if rid == entity.id:
                    stats["entities_created"] += 1
                else:
                    stats["entities_merged"] += 1

        # ── Step 2: 提取关系 ────────────────────
        relations = self._extract_relations(entities, profile, research_bundle)
        for rel in relations:
            rid = self._gs.add_edge(rel)
            if rid:
                stats["relations_added"] += 1

        # ── Step 3: 创建 LongTermMemory → VectorStore ──
        self._index_to_vector(company_name, profile, risk, pipeline_id)

        # ── Step 4: 提取 Insight ─────────────────
        insights = self._extract_insights(research_bundle, entities)
        for ins in insights:
            self._gs.add_node(ins)
            stats["insights"] += 1
            # Insight → 关联边的实体的边
            for entity in entities:
                self._gs.add_edge(DerivedFromEdge(
                    source_node_id=ins.id,
                    target_node_id=entity.id,
                    derivation_rule="research_pipeline",
                ))

        logger.info(
            "Distillation done: +%d entities, ~%d merged, +%d relations, +%d insights",
            stats["entities_created"], stats["entities_merged"],
            stats["relations_added"], stats["insights"],
        )
        return stats

    # ── 实体提取 ──────────────────────────────────

    def _extract_entities(
        self,
        company_name: str,
        profile: dict,
        risk: dict,
        identity: dict,
        bundle: dict,
    ) -> list[GraphNode]:
        """从 ResearchBundle 提取所有实体"""
        entities: list[GraphNode] = []

        # 1. Company node
        comp = CompanyNode(
            name=company_name,
            unified_social_credit_code=identity.get("unified_social_credit_code", ""),
            industry=profile.get("industry", ""),
            employee_range=profile.get("employee_count_range", ""),
            revenue_range=profile.get("revenue_range", ""),
            risk_score=float(risk.get("risk_score", 0)),
            status=profile.get("status", ""),
            properties={
                "legal_person": profile.get("legal_person", ""),
                "registered_capital": profile.get("registered_capital", ""),
                "established_date": profile.get("established_date", ""),
                "address": profile.get("address", ""),
                "business_scope": profile.get("business_scope", ""),
                "website": profile.get("website", ""),
            },
            sources=[f"pipeline_{bundle.get('company_name', '')}"],
        )
        entities.append(comp)

        # 2. Industry node (if new)
        industry = profile.get("industry", "")
        if industry:
            entities.append(IndustryNode(
                name=industry,
                category=industry,
                properties={"source": "enrichment"},
            ))

        # 3. Person nodes (from key_people or person_background)
        people = profile.get("key_people", []) or bundle.get("person_background", [])
        if isinstance(people, dict):
            people = [people]
        for p in people[:5]:
            if isinstance(p, dict) and p.get("name"):
                person = PersonNode(
                    name=p.get("name", ""),
                    title=p.get("title", ""),
                    company=company_name,
                    phone=p.get("phone", "") or "",
                    email=p.get("email", "") or "",
                    properties=p,
                    sources=[f"pipeline_{company_name}"],
                )
                entities.append(person)

        # 4. Contact nodes (email/phone)
        for ct in profile.get("contact_emails", [])[:3]:
            if ct:
                entities.append(BDContactNode(
                    name=f"email:{ct}",
                    contact_type="email",
                    value=ct,
                    owner_company=company_name,
                ))
        for ph in profile.get("contact_phones", [])[:3]:
            if ph:
                entities.append(BDContactNode(
                    name=f"phone:{ph}",
                    contact_type="phone",
                    value=ph,
                    owner_company=company_name,
                ))

        # 5. Event nodes (risk events)
        court_cases = risk.get("court_cases", []) or []
        for case in court_cases[:5]:
            if isinstance(case, dict):
                entities.append(EventNode(
                    name=f"case:{case.get('case_no', '')}",
                    event_type="lawsuit",
                    date=str(case.get("judgment_date", "")),
                    description=f"{case.get('plaintiff', '')} v {case.get('defendant', '')}",
                    amount_yuan=float(case.get("amount_yuan", 0)),
                ))

        abnormal = risk.get("abnormal_details", []) or []
        for ab in abnormal[:5]:
            if isinstance(ab, dict):
                entities.append(EventNode(
                    name=f"abnormal:{ab.get('name', '')}",
                    event_type="abnormal_operation",
                    date=str(ab.get("date", "")),
                    description=ab.get("reason", ""),
                ))

        return entities

    # ── 关系提取 ──────────────────────────────────

    def _extract_relations(
        self, entities: list[GraphNode], profile: dict, bundle: dict,
    ) -> list[GraphEdge]:
        """从实体列表中提取关系"""
        relations: list[GraphEdge] = []

        company_node = None
        industry_node = None
        person_nodes = []
        contact_nodes = []
        event_nodes = []

        for e in entities:
            if isinstance(e, CompanyNode):
                company_node = e
            elif isinstance(e, IndustryNode):
                industry_node = e
            elif isinstance(e, PersonNode):
                person_nodes.append(e)
            elif isinstance(e, BDContactNode):
                contact_nodes.append(e)
            elif isinstance(e, EventNode):
                event_nodes.append(e)

        if not company_node:
            return relations

        # Company → Industry
        if industry_node:
            relations.append(BelongsToIndustryEdge(
                source_node_id=company_node.id,
                target_node_id=industry_node.id,
                confidence=0.95,
                sources=[f"enrichment_{company_node.name}"],
            ))

        # Company ← Person (employ)
        for person in person_nodes:
            relations.append(GraphEdge(
                edge_type=EdgeType.EMPLOYS,
                source_node_id=company_node.id,
                target_node_id=person.id,
                confidence=0.85,
                properties={"title": person.title},
                sources=[f"pipeline_{company_node.name}"],
            ))

        # Company → Contact
        for ct in contact_nodes:
            relations.append(HasContactEdge(
                source_node_id=company_node.id,
                target_node_id=ct.id,
                confidence=0.9,
                properties={"contact_type": ct.contact_type},
            ))

        # Company → Event
        for ev in event_nodes:
            relations.append(GraphEdge(
                edge_type=EdgeType.PARTICIPATED_IN,
                source_node_id=company_node.id,
                target_node_id=ev.id,
                confidence=0.9,
                properties={"event_type": ev.event_type},
            ))

        # Competitors → Company (COMPETES_WITH)
        competitors = bundle.get("competitors", []) or []
        for comp_name in competitors[:5]:
            if isinstance(comp_name, str) and comp_name:
                # 查找是否已有该竞争者节点
                existing = self._gs.find_nodes(name=comp_name, node_type=NodeType.COMPANY)
                if existing:
                    target_id = existing[0].id
                else:
                    comp_node = CompanyNode(name=comp_name)
                    target_id = self._gs.add_node(comp_node)
                relations.append(CompetesWithEdge(
                    source_node_id=company_node.id,
                    target_node_id=target_id,
                    confidence=0.7,
                    competition_type="direct",
                    sources=[f"pipeline_{company_node.name}"],
                ))

        # 地址 → LocatedIn
        address = profile.get("address", "")
        if address:
            city_match = re.search(r"([\u4e00-\u9fff]{2,4}[市])", address)
            if city_match:
                city_name = city_match.group(1)
                city_nodes = self._gs.find_nodes(name=city_name, node_type=None)
                if not city_nodes:
                    city_node = GraphNode(node_type=NodeType.INDUSTRY, name=city_name)
                    city_id = self._gs.add_node(city_node)
                else:
                    city_id = city_nodes[0].id
                relations.append(LocatedInEdge(
                    source_node_id=company_node.id,
                    target_node_id=city_id,
                    address=address,
                    confidence=0.9,
                ))

        return relations

    # ── Insight 提取 ───────────────────────────────

    def _extract_insights(
        self, bundle: dict, entities: list[GraphNode],
    ) -> list[InsightNode]:
        """从 ResearchBundle 提取洞察"""
        insights: list[InsightNode] = []

        # 行业分析
        industry_analysis = bundle.get("industry_analysis", "")
        if industry_analysis and len(industry_analysis) > 20:
            insights.append(InsightNode(
                name=f"industry_insight_{bundle.get('company_name', '')}",
                insight_type="market",
                content=industry_analysis[:500],
                related_entities=[e.id for e in entities[:3]],
            ))

        # 风险洞察
        risk = bundle.get("risk", {}) or {}
        risk_factors = risk.get("risk_factors", [])
        if risk_factors:
            insights.append(InsightNode(
                name=f"risk_insight_{bundle.get('company_name', '')}",
                insight_type="risk",
                content="Risk factors: " + "; ".join(risk_factors),
                related_entities=[e.id for e in entities[:3]],
            ))

        return insights

    # ── Vector Index ───────────────────────────────

    def _index_to_vector(
        self, company_name: str, profile: dict, risk: dict, pipeline_id: str,
    ) -> None:
        """LongTermMemory → VectorStore"""
        ltm = LongTermMemory(
            company_name=company_name,
            profile_summary=(
                f"{company_name} - {profile.get('industry', '')} - "
                f"风险评分: {risk.get('risk_score', 0)}. "
                f"{profile.get('company_description', '')[:200]}"
            ),
            profile_json=profile,
            risk_json=risk,
            industry=profile.get("industry", ""),
            employee_range=profile.get("employee_count_range", ""),
            revenue_range=profile.get("revenue_range", ""),
            risk_score=float(risk.get("risk_score", 0)),
            research_count=1,
            tags=profile.get("tags", []),
            bd_notes=profile.get("bd_notes", ""),
        )

        entry = ltm.to_memory_entry()
        entry.source_pipeline_id = pipeline_id
        self._vs.add(entry)
