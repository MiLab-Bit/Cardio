# byou/intake/identity/graph_nx.py
"""Identity Graph + NetworkX backend.

Extends IdentityGraph with:
  - NetworkX DiGraph backend (for graph algorithms)
  - Shortest path (how are two people related?)
  - Community detection (which people belong together?)
  - Graph queries (find all people at company X)

Falls back to in-memory dict backend if NetworkX is not available.
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.identity.graph import (
    BindingType,
    IdentityBinding,
    IdentityGraph,
    IdentityNode,
    MatchDecisionType,
    MatchResult,
    MergeResult,
    NodeType,
)

logger = logging.getLogger(__name__)

try:
    import networkx as nx

    _HAS_NX = True
except ImportError:
    _HAS_NX = False
    logger.warning("NetworkX not available — graph algorithms disabled")


class IdentityGraphNX(IdentityGraph):
    """IdentityGraph with NetworkX backend for graph algorithms.

    Maintains BOTH:
      - dict backend (for fast node/binding lookup, same API as IdentityGraph)
      - NetworkX DiGraph (for graph algorithms)

    Keeps them in sync on every mutating operation.
    """

    def __init__(self) -> None:
        super().__init__()
        if _HAS_NX:
            self._nxg: nx.DiGraph = nx.DiGraph()
        else:
            self._nxg = None  # type: ignore

    # ── Node ops (sync NX) ─────────────────────────────

    def add_node(self, node: IdentityNode) -> None:
        super().add_node(node)
        if self._nxg is not None:
            self._nxg.add_node(node.node_id, **node.model_dump())

    def remove_node(self, node_id: str) -> None:
        super().remove_node(node_id)
        if self._nxg is not None and self._nxg.has_node(node_id):
            self._nxg.remove_node(node_id)

    # ── Binding ops (sync NX) ─────────────────────────

    def add_binding(self, binding: IdentityBinding) -> None:
        super().add_binding(binding)
        if self._nxg is not None:
            self._nxg.add_edge(
                binding.source_id,
                binding.target_id,
                binding_type=binding.binding_type.value,
                confidence=binding.confidence,
                binding_id=binding.binding_id,
            )

    def remove_binding(self, binding_id: str) -> None:
        # Find and remove from NX too
        if binding_id in self._bindings:
            b = self._bindings[binding_id]
            if self._nxg is not None and self._nxg.has_edge(b.source_id, b.target_id):
                self._nxg.remove_edge(b.source_id, b.target_id)
        super().remove_binding(binding_id)

    def deactivate_binding(self, binding_id: str) -> None:
        super().deactivate_binding(binding_id)
        # NX graph doesn't model "active" — edge stays, filter at query time

    # ── Graph algorithms ─────────────────────────────────

    def shortest_path(self, source: str, target: str) -> list[str] | None:
        """Find shortest path between two identity nodes.

        Returns list of node IDs [source, ..., target], or None.

        Example:
            graph.shortest_path("uid_alice", "uid_bob")
            → ["uid_alice", "bid_staff1", "uid_bob"]
            (meaning: Alice met Bob via staff 1)
        """
        if not _HAS_NX or self._nxg is None:
            logger.warning("NetworkX not available for shortest_path")
            return None
        try:
            path = nx.shortest_path(self._nxg, source=source, target=target)
            return list(path)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def all_paths(self, source: str, target: str, cutoff: int = 4) -> list[list[str]]:
        """Find all paths up to `cutoff` hops."""
        if not _HAS_NX or self._nxg is None:
            return []
        try:
            return list(nx.all_simple_paths(self._nxg, source, target, cutoff=cutoff))
        except nx.NodeNotFound:
            return []

    def connected_components(self) -> list[set[str]]:
        """Find connected components (undirected view)."""
        if not _HAS_NX or self._nxg is None:
            return [set(self._nodes.keys())]
        return list(nx.weakly_connected_components(self._nxg))

    def pagerank(self, max_iter: int = 100) -> dict[str, float]:
        """Compute PageRank (which identities are most "central"?)."""
        if not _HAS_NX or self._nxg is None or self._nxg.number_of_nodes() == 0:
            return {}
        try:
            return nx.pagerank(self._nxg, max_iter=max_iter)
        except nx.PowerIterationFailedConvergence:
            logger.warning("PageRank did not converge")
            return {}

    def suggest_connections(self, uid: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Suggest possible connections for a UID based on graph structure.

        Uses:
          - Common neighbors (friends-of-friends)
          - Same binding types
        """
        if not _HAS_NX or self._nxg is None:
            return []

        neighbors = set(self._nxg.successors(uid)) | set(self._nxg.predecessors(uid))
        suggestions: dict[str, float] = {}

        for neighbor in neighbors:
            for nn in set(self._nxg.successors(neighbor)) | set(self._nxg.predecessors(neighbor)):
                if nn == uid or nn in neighbors:
                    continue
                suggestions[nn] = suggestions.get(nn, 0.0) + 1.0

        # Sort by connection strength
        ranked = sorted(suggestions.items(), key=lambda x: x[1], reverse=True)
        return [
            {"uid": uid, "strength": score, "via": uid}
            for uid, score in ranked[:top_k]
        ]

    # ── Enhanced queries ─────────────────────────────────

    def find_by_binding_type(self, binding_type: BindingType) -> list[IdentityBinding]:
        """Find all bindings of a given type."""
        return [b for b in self._bindings.values() if b.binding_type == binding_type and b.is_active]

    def get_neighbors(self, node_id: str) -> list[IdentityNode]:
        """Get all neighbor nodes (both directions)."""
        result: list[IdentityNode] = []
        for bid in self._by_source.get(node_id, []):
            b = self._bindings[bid]
            node = self._nodes.get(b.target_id)
            if node:
                result.append(node)
        for bid in self._by_target.get(node_id, []):
            b = self._bindings[bid]
            node = self._nodes.get(b.source_id)
            if node:
                result.append(node)
        return result

    # ── Stats (enhanced) ──────────────────────────────

    def nx_stats(self) -> dict[str, Any]:
        """Return NetworkX graph statistics."""
        if not _HAS_NX or self._nxg is None:
            return {"nx_available": False}
        return {
            "nx_available": True,
            "nodes": self._nxg.number_of_nodes(),
            "edges": self._nxg.number_of_edges(),
            "density": nx.density(self._nxg),
            "is_connected": nx.is_weakly_connected(self._nxg) if self._nxg.number_of_nodes() > 0 else False,
            "diameter": nx.diameter(self._nxg.to_undirected()) if self._nxg.number_of_nodes() > 1 and nx.is_connected(self._nxg.to_undirected()) else None,
        }

    # ── Save/Load (override to also save NX) ─────────

    def save(self, path: str | Path) -> None:  # type: ignore[override]
        """Save graph (delegates to parent, NX is rebuilt on load)."""
        super().save(path)
        # NX graph is rebuilt from nodes/bindings on load, no need to save separately

    @classmethod
    def load(cls, path: str | Path) -> IdentityGraph:  # type: ignore[override]
        """Load graph (rebuilds NX graph from saved data)."""
        instance = cls()
        # Use parent load, which loads nodes + bindings
        # Then sync to NX
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # Parent load already handles this via IdentityGraph.load()
        graph = IdentityGraph.load(path)
        if _HAS_NX:
            instance._nodes = graph._nodes
            instance._bindings = graph._bindings
            instance._by_source = graph._by_source
            instance._by_target = graph._by_target
            instance._vpids = graph._vpids
            # Rebuild NX graph
            for node in instance._nodes.values():
                instance._nxg.add_node(node.node_id, **node.model_dump())
            for binding in instance._bindings.values():
                instance._nxg.add_edge(
                    binding.source_id,
                    binding.target_id,
                    binding_type=binding.binding_type.value,
                    confidence=binding.confidence,
                    binding_id=binding.binding_id,
                )
        return instance
