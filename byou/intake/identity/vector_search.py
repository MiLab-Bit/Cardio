# byou/intake/identity/vector_search.py
"""Vector-backed identity search — extends IdentityGraph with fast similarity search.

Wraps IdentityGraph + VectorStore:
  - Voiceprint embeddings → VectorStore (fast ANN search)
  - Name/company embeddings → VectorStore (semantic matching)
  - Falls back to IdentityGraph for non-vector queries.

Usage:
    graph = IdentityGraph()
    vs = VectorBackedIdentityGraph(graph, store)
    result = vs.match_voiceprint_vector(query_embedding)
"""

from __future__ import annotations

import logging
from typing import Any

from byou.core.vector_store import VectorStore
from byou.intake.identity.graph import (
    IdentityGraph,
    MatchDecisionType,
    MatchResult,
)

logger = logging.getLogger(__name__)


class VectorBackedIdentityGraph:
    """IdentityGraph + VectorStore for fast similarity search."""

    def __init__(
        self,
        identity_graph: IdentityGraph,
        vector_store: VectorStore | None = None,
        embedding_dim: int = 1536,
    ):
        self._graph = identity_graph
        self._store = vector_store or VectorStore(dim=embedding_dim)
        self._embedding_dim = embedding_dim

    # ── Voiceprint search (vector-backed) ──────────────────────

    def register_voiceprint_vector(self, uid: str, embedding: list[float]) -> None:
        """Register a voiceprint in both graph and vector store."""
        self._graph.register_voiceprint(uid, embedding)
        # Use UID + hash of embedding as vector ID to allow multiple embeddings per UID
        vec_id = f"vp_{uid}_{hash(tuple(embedding))}"
        self._store.add(vec_id, embedding, metadata={"uid": uid, "type": "voiceprint"})

    def match_voiceprint_vector(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        threshold_auto: float = 0.85,
        threshold_ambiguous: float = 0.5,
    ) -> MatchResult:
        """Match voiceprint using vector store (fast ANN).

        Returns MatchResult with candidates grouped by UID.
        """
        results = self._store.search(
            query_embedding,
            top_k=top_k * 3,  # get more to de-duplicate by UID
            filter_fn=lambda m: m.get("type") == "voiceprint",
        )

        # De-duplicate by UID, keep best score
        uid_best: dict[str, float] = {}
        for r in results:
            uid = r["metadata"].get("uid", "")
            if uid:
                score = r["score"]
                if uid not in uid_best or score > uid_best[uid]:
                    uid_best[uid] = score

        # Sort by score
        sorted_uids = sorted(uid_best.items(), key=lambda x: x[1], reverse=True)
        candidates = [
            {"uid": uid, "score": round(score, 4), "evidence": [f"voiceprint_match:{uid}"]}
            for uid, score in sorted_uids
        ]

        return self._to_match_result(candidates, threshold_auto, threshold_ambiguous)

    # ── Name search (vector-backed, optional) ──────────────────────

    def register_name_embedding(self, uid: str, name: str, embedding: list[float]) -> None:
        """Register a name embedding for semantic name matching."""
        vec_id = f"name_{uid}_{hash(name)}"
        self._store.add(vec_id, embedding, metadata={"uid": uid, "type": "name", "name": name})

    def match_name_vector(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search by name embedding (semantic name matching)."""
        results = self._store.search(
            query_embedding,
            top_k=top_k,
            filter_fn=lambda m: m.get("type") == "name",
        )
        return [
            {"uid": r["metadata"]["uid"], "score": r["score"], "name": r["metadata"].get("name", "")}
            for r in results if r["score"] >= threshold
        ]

    # ── Persistence ─────────────────────────────────────────────

    def save(self, graph_path: str, vector_path: str) -> None:
        """Save both graph and vector store."""
        self._graph.save(graph_path)
        self._store.persist_path = vector_path  # type: ignore
        self._store.save()

    def load(self, graph_path: str, vector_path: str) -> None:
        """Load both graph and vector store."""
        self._graph = IdentityGraph.load(graph_path)
        self._store = VectorStore(persist_path=vector_path)
        self._store.load()

    # ── Delegation to underlying graph ──────────────────────

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to the underlying IdentityGraph."""
        return getattr(self._graph, name)

    # ── Internal ─────────────────────────────────────────────

    def _to_match_result(
        self,
        candidates: list[dict],
        threshold_auto: float,
        threshold_ambiguous: float,
    ) -> MatchResult:
        if not candidates:
            return MatchResult(
                query_id="voiceprint_vector",
                decision=MatchDecisionType.NO_MATCH,
                candidates=[],
                requires_review=False,
            )

        best = candidates[0]
        if best["score"] >= threshold_auto and len(candidates) == 1:
            return MatchResult(
                query_id="voiceprint_vector",
                decision=MatchDecisionType.AUTO_MATCH,
                candidates=candidates[:3],
                requires_review=False,
            )
        elif best["score"] >= threshold_auto:
            return MatchResult(
                query_id="voiceprint_vector",
                decision=MatchDecisionType.AMBIGUOUS,
                candidates=candidates[:5],
                requires_review=True,
                review_reason=f"Multiple candidates above {threshold_auto}",
            )
        else:
            return MatchResult(
                query_id="voiceprint_vector",
                decision=MatchDecisionType.AMBIGUOUS,
                candidates=candidates[:5],
                requires_review=best["score"] >= threshold_ambiguous,
                review_reason=f"Best match {best['score']:.2f} < auto threshold {threshold_auto}",
            )
