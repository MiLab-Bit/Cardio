"""Byou Memory — GraphStore (NetworkX + Neo4j).

Phase 2: 知识图谱存储引擎。

设计:
- 默认用 NetworkX (零依赖, MVP)
- 可选 Neo4j (生产化)
- 节点/边 CRUD + 图查询 + 冲突解决
- 子图抽取 + 路径查询
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

import networkx as nx

from byou.memory.types import (
    GraphNode, GraphEdge, NodeType, EdgeType,
    CompanyNode, PersonNode, IndustryNode, EventNode,
    BDContactNode, InsightNode,
)

logger = logging.getLogger(__name__)


class GraphStore:
    """知识图谱存储引擎。

    Node → NetworkX node (id=node.id, **node.model_dump())
    Edge → NetworkX edge (source_id → target_id, **edge.model_dump())
    """

    def __init__(self, use_neo4j: bool = False, neo4j_uri: str = "", neo4j_auth: tuple = ()):
        self._graph = nx.MultiDiGraph()
        self._node_index: dict[str, list[str]] = defaultdict(list)  # name -> [node_ids]
        self._alias_index: dict[str, str] = {}  # alias → primary_id
        self._use_neo4j = use_neo4j
        self._neo4j_driver = None

        if use_neo4j:
            try:
                from neo4j import GraphDatabase
                self._neo4j_driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
                logger.info("Neo4j connected: %s", neo4j_uri)
            except ImportError:
                logger.warning("neo4j not installed, fallback to NetworkX")
            except Exception as e:
                logger.warning("Neo4j connection failed: %s", e)

    # ── Node CRUD ────────────────────────────────────

    def add_node(self, node: GraphNode) -> str:
        """添加节点 (自动去重)"""
        # 检查是否已存在
        existing = self._find_node(node.name, node.node_type)
        if existing:
            return self._merge_node(existing, node)

        self._graph.add_node(node.id, **node.model_dump())
        self._node_index[node.name].append(node.id)
        for alias in node.aliases:
            self._alias_index[alias] = node.id
        return node.id

    def get_node(self, node_id: str) -> GraphNode | None:
        """获取节点"""
        if node_id not in self._graph:
            return None
        data = dict(self._graph.nodes[node_id])
        return self._dict_to_node(data)

    def find_nodes(
        self, name: str = "", node_type: NodeType | None = None,
    ) -> list[GraphNode]:
        """按名称搜索节点"""
        results: list[GraphNode] = []
        node_ids = self._node_index.get(name, [])

        if not node_ids:
            # 模糊搜索
            for n, ids in self._node_index.items():
                if name.lower() in n.lower():
                    node_ids.extend(ids)

        for nid in node_ids[:20]:
            node = self.get_node(nid)
            if node and (node_type is None or node.node_type == node_type):
                results.append(node)

        return results

    def update_node(self, node: GraphNode) -> str:
        """更新节点"""
        if node.id in self._graph:
            self._graph.nodes[node.id].update(node.model_dump())
        else:
            self.add_node(node)
        return node.id

    def delete_node(self, node_id: str) -> bool:
        """删除节点及其关联边"""
        if node_id not in self._graph:
            return False
        self._graph.remove_node(node_id)
        # 清理索引
        for name, ids in list(self._node_index.items()):
            self._node_index[name] = [i for i in ids if i != node_id]
        return True

    # ── Edge CRUD ────────────────────────────────────

    def add_edge(self, edge: GraphEdge) -> str:
        """添加边 (自动去重)"""
        existing = self._find_edge(edge.source_node_id, edge.target_node_id, edge.edge_type)
        if existing:
            return existing.id

        self._graph.add_edge(
            edge.source_node_id,
            edge.target_node_id,
            key=edge.id,
            **edge.model_dump(),
        )
        return edge.id

    def get_edges(
        self,
        source_id: str = "",
        target_id: str = "",
        edge_type: EdgeType | None = None,
    ) -> list[GraphEdge]:
        """获取边"""
        results: list[GraphEdge] = []

        if source_id and target_id:
            edges_data = self._graph.get_edge_data(source_id, target_id, default={})
            for key, data in edges_data.items():
                if edge_type and data.get("edge_type") != edge_type.value:
                    continue
                results.append(self._dict_to_edge(data))
        else:
            for u, v, key, data in self._graph.edges(keys=True, data=True):
                if source_id and u != source_id:
                    continue
                if target_id and v != target_id:
                    continue
                if edge_type and data.get("edge_type") != edge_type.value:
                    continue
                results.append(self._dict_to_edge(data))

        return results

    def delete_edge(self, edge_id: str) -> bool:
        """删除边"""
        for u, v, key in list(self._graph.edges(keys=True)):
            if key == edge_id:
                self._graph.remove_edge(u, v, key=key)
                return True
        return False

    # ── 图查询 ──────────────────────────────────────

    def get_neighbors(
        self, node_id: str, edge_types: list[EdgeType] | None = None, max_depth: int = 1,
    ) -> dict[str, list[dict[str, Any]]]:
        """获取节点的邻居"""
        result: dict[str, list[dict[str, Any]]] = {}
        if node_id not in self._graph:
            return result

        for neighbor in self._graph.neighbors(node_id):
            edges_data = self._graph.get_edge_data(node_id, neighbor, default={})
            for key, data in edges_data.items():
                et = data.get("edge_type", "")
                if edge_types and et not in [e.value for e in edge_types]:
                    continue

                neighbor_node = self.get_node(neighbor)
                if neighbor_node:
                    if et not in result:
                        result[et] = []
                    result[et].append({
                        "node": neighbor_node.model_dump(),
                        "edge": dict(data),
                    })

        # 递归
        if max_depth > 1:
            for neighbor in list(self._graph.neighbors(node_id)):
                deeper = self.get_neighbors(neighbor, edge_types, max_depth - 1)
                for k, v in deeper.items():
                    if k not in result:
                        result[k] = []
                    result[k].extend(v)

        return result

    def shortest_path(
        self, source_id: str, target_id: str,
    ) -> list[dict[str, Any]] | None:
        """最短路径"""
        try:
            path = nx.shortest_path(self._graph, source=source_id, target=target_id)
            result = []
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                edges_data = self._graph.get_edge_data(u, v, default={})
                result.append({
                    "from": self.get_node(u).model_dump() if self.get_node(u) else {},
                    "to": self.get_node(v).model_dump() if self.get_node(v) else {},
                    "edges": [dict(d) for d in edges_data.values()],
                })
            return result
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def subgraph(
        self, node_ids: list[str], depth: int = 1,
    ) -> nx.MultiDiGraph:
        """抽取子图"""
        nodes = set(node_ids)
        for _ in range(depth):
            neighbors = set()
            for nid in list(nodes):
                for u, v in self._graph.edges():
                    if u == nid:
                        neighbors.add(v)
                    if v == nid:
                        neighbors.add(u)
            nodes.update(neighbors)
        return self._graph.subgraph(list(nodes)).copy()

    def get_competitors(self, company_node_id: str) -> list[CompanyNode]:
        """获取竞争对手"""
        competitors: list[CompanyNode] = []
        edges = self.get_edges(
            source_id=company_node_id,
            edge_type=EdgeType.COMPETES_WITH,
        )
        for edge in edges:
            node = self.get_node(edge.target_node_id)
            if node and isinstance(node, CompanyNode):
                competitors.append(node)
        return competitors

    def get_equity_tree(self, company_node_id: str, max_depth: int = 3) -> dict[str, Any]:
        """股权穿透"""
        tree: dict[str, Any] = {"company": company_node_id, "investors": []}

        edges = self.get_edges(
            target_id=company_node_id,
            edge_type=EdgeType.INVESTS_IN,
        )
        for edge in edges:
            investor = self.get_node(edge.source_node_id)
            if investor:
                info = {
                    "investor": investor.model_dump(),
                    "stake": edge.properties.get("stake_percent", 0),
                    "amount": edge.properties.get("amount_yuan", 0),
                }
                tree["investors"].append(info)

        # 递归 (简化: 只查一层)
        return tree

    # ── 统计 ────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        """图谱统计"""
        return {
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "company_nodes": len(self.find_nodes(node_type=NodeType.COMPANY)),
            "person_nodes": len(self.find_nodes(node_type=NodeType.PERSON)),
            "industry_nodes": len(self.find_nodes(node_type=NodeType.INDUSTRY)),
            "insight_nodes": len(self.find_nodes(node_type=NodeType.INSIGHT)),
        }

    # ── 内部帮助函数 ─────────────────────────────────

    def _find_node(self, name: str, node_type: NodeType) -> GraphNode | None:
        """查找是否已存在同名同类型节点"""
        existing = self.find_nodes(name=name, node_type=node_type)
        return existing[0] if existing else None

    def _merge_node(self, existing: GraphNode, incoming: GraphNode) -> str:
        """合并节点: 更新属性，保留更新更权威的数据"""
        from datetime import timezone

        # 1. 更新 properties (merge)
        existing.properties.update(incoming.properties)

        # 2. 更新 aliases
        existing.aliases = list(set(existing.aliases + incoming.aliases))

        # 3. 更新 sources
        existing.sources = list(set(existing.sources + incoming.sources))

        # 4. 置信度取最高
        existing.confidence = max(existing.confidence, incoming.confidence)

        # 5. 更新时间
        existing.updated_at = incoming.created_at or datetime.now(timezone.utc)

        # 6. 写回
        self._graph.nodes[existing.id].update(existing.model_dump())
        return existing.id

    def _find_edge(self, source: str, target: str, edge_type: EdgeType) -> GraphEdge | None:
        """查找是否已存在同类型边"""
        edges_data = self._graph.get_edge_data(source, target, default={})
        for key, data in edges_data.items():
            if data.get("edge_type") == edge_type.value:
                return self._dict_to_edge(data)
        return None

    @staticmethod
    def _dict_to_node(data: dict[str, Any]) -> GraphNode:
        """dict → 对应节点类型"""
        node_type = data.get("node_type", "company")
        type_map = {
            NodeType.COMPANY: CompanyNode,
            NodeType.PERSON: PersonNode,
            NodeType.INDUSTRY: IndustryNode,
            NodeType.EVENT: EventNode,
            NodeType.BD_CONTACT: BDContactNode,
            NodeType.INSIGHT: InsightNode,
        }
        cls = type_map.get(node_type, GraphNode)
        return cls(**data)

    @staticmethod
    def _dict_to_edge(data: dict[str, Any]) -> GraphEdge:
        """dict → GraphEdge"""
        return GraphEdge(**data)
