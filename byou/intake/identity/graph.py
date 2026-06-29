# byou/intake/identity/graph.py
"""Minimal Identity Graph — UID/BID/VPID/PersonCandidate nodes + typed edges.

v2: in-memory graph.  v3: persistent (Neo4j or NetworkX + DB).

Design:
  - UID = external contact (immutable, mergable)
  - BID = internal BD staff
  - VPID = voiceprint profile (versioned)
  - PersonCandidate = provisional identity (→ UID on confirm)
  - IdentityBinding = typed edge with confidence + evidence
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# Node types
# ══════════════════════════════════════════════════════════

class NodeType(str, Enum):
    UID = "uid"
    BID = "bid"
    VPID = "vpid"
    PERSON_CANDIDATE = "person_candidate"


class BindingType(str, Enum):
    VOICEPRINT_MATCH = "voiceprint_match"     # VPID → UID via voiceprint similarity
    CARD_MATCH = "card_match"                # PersonCandidate → UID via 名片 fields
    CO_LOCATION = "co_location"              # same session co-occurrence
    MANUAL = "manual"                         # human reviewer resolved
    EXTERNAL_REF = "external_ref"            # CRM ID, LinkedIn, etc.
    MERGED_INTO = "merged_into"              # merge event: old UID → new UID


class MatchDecisionType(str, Enum):
    AUTO_MATCH = "auto_match"        # confidence ≥ 0.85
    AMBIGUOUS = "ambiguous"          # 0.5 ≤ confidence < 0.85
    NO_MATCH = "no_match"           # confidence < 0.5
    CONFLICT = "conflict"           # contradictory evidence


# ══════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════

class IdentityNode(BaseModel):
    """A node in the identity graph."""
    node_id: str                               # uid_xxx, bid_xxx, vpid_xxx, etc.
    node_type: NodeType
    label: str = ""                            # display name
    aliases: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentityBinding(BaseModel):
    """A typed, weighted edge between two identity nodes."""
    binding_id: str = Field(default_factory=lambda: f"bind_{uuid4().hex[:8]}")
    source_id: str                             # source node
    target_id: str                             # target node
    binding_type: BindingType
    confidence: float = 0.0                    # 0-1
    evidence_refs: list[str] = Field(default_factory=list)  # EIDs
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True                     # soft-delete for merges
    metadata: dict[str, Any] = Field(default_factory=dict)


class MatchResult(BaseModel):
    """Result of matching a speaker/card to known identities."""
    query_id: str                              # what we're matching (VPID or PersonCandidate)
    decision: MatchDecisionType
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    # each candidate: {uid: str, score: float, evidence: list[str]}
    requires_review: bool = False
    review_reason: str = ""


class MergeResult(BaseModel):
    """Result of merging uid_a into uid_b."""
    source_uid: str
    target_uid: str
    success: bool
    bindings_migrated: int = 0
    aliases_merged: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ══════════════════════════════════════════════════════════
# IdentityGraph — in-memory
# ══════════════════════════════════════════════════════════

class IdentityGraph:
    """Minimal in-memory identity graph.

    v2: dict-based.  v3: NetworkX or graph DB.
    """

    def __init__(self, vector_store: "VectorStore | None" = None) -> None:
        self._nodes: dict[str, IdentityNode] = {}       # node_id → node
        self._bindings: dict[str, IdentityBinding] = {} # binding_id → binding
        self._by_source: dict[str, list[str]] = {}      # source_id → [binding_id]
        self._by_target: dict[str, list[str]] = {}      # target_id → [binding_id]
        self._vpids: dict[str, list[float]] = {}         # uid → [embedding] for matching
        self._vector_store = vector_store                # optional VectorStore for ANN

    # ── Node ops ─────────────────────────────────────

    def add_node(self, node: IdentityNode) -> None:
        self._nodes[node.node_id] = node

    def get_node(self, node_id: str) -> IdentityNode | None:
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> None:
        if node_id in self._nodes:
            del self._nodes[node_id]
        # clean bindings
        for bid in list(self._by_source.get(node_id, [])):
            self.remove_binding(bid)
        for bid in list(self._by_target.get(node_id, [])):
            self.remove_binding(bid)
        self._by_source.pop(node_id, None)
        self._by_target.pop(node_id, None)

    def find_by_alias(self, alias: str) -> list[IdentityNode]:
        return [
            n for n in self._nodes.values()
            if alias.lower() in [a.lower() for a in n.aliases] + [n.label.lower()]
        ]

    def find_by_type(self, node_type: NodeType) -> list[IdentityNode]:
        return [n for n in self._nodes.values() if n.node_type == node_type]

    def list_nodes(self) -> list[IdentityNode]:
        return list(self._nodes.values())

    # ── Binding ops ──────────────────────────────────

    def add_binding(self, binding: IdentityBinding) -> None:
        self._bindings[binding.binding_id] = binding
        self._by_source.setdefault(binding.source_id, []).append(binding.binding_id)
        self._by_target.setdefault(binding.target_id, []).append(binding.binding_id)

    def get_bindings_for(self, node_id: str) -> list[IdentityBinding]:
        bind_ids = (
            self._by_source.get(node_id, [])
            + self._by_target.get(node_id, [])
        )
        return [self._bindings[bid] for bid in bind_ids if bid in self._bindings]

    def get_bindings_by_type(
        self, node_id: str, binding_type: BindingType,
    ) -> list[IdentityBinding]:
        return [
            b for b in self.get_bindings_for(node_id)
            if b.binding_type == binding_type and b.is_active
        ]

    def remove_binding(self, binding_id: str) -> None:
        if binding_id in self._bindings:
            b = self._bindings.pop(binding_id)
            for idx in [self._by_source, self._by_target]:
                idx.get(b.source_id, [])
                if binding_id in idx.get(b.source_id, []):
                    idx[b.source_id].remove(binding_id)

    def deactivate_binding(self, binding_id: str) -> None:
        if binding_id in self._bindings:
            self._bindings[binding_id].is_active = False

    # ── Voiceprint ops ───────────────────────────────

    def register_voiceprint(self, uid: str, embedding: list[float]) -> None:
        self._vpids.setdefault(uid, []).append(embedding)
        # Also index in VectorStore for fast ANN search
        if self._vector_store:
            try:
                idx = len(self._vpids[uid])
                self._vector_store.add(
                    id=f"vp_{uid}_{idx}",
                    embedding=embedding,
                    metadata={"uid": uid, "type": "voiceprint"},
                )
            except Exception as e:
                logger.warning("VectorStore register failed: %s", e)

    def get_voiceprints(self, uid: str) -> list[list[float]]:
        return self._vpids.get(uid, [])

    # ── Matching ─────────────────────────────────────

    def match_voiceprint(
        self, embedding: list[float], threshold_auto: float = 0.85,
        threshold_ambiguous: float = 0.5,
    ) -> MatchResult:
        """Match a voiceprint embedding to known UIDs.

        Simplest cosine similarity.  v3: FAISS/HNSW index.
        """
        # Use VectorStore for ANN search if available
        if self._vector_store:
            ann_results = self._vector_store.search(embedding, k=5)
            candidates = []
            for r in ann_results:
                if r["score"] >= threshold_ambiguous:
                    candidates.append({
                        "uid": r["id"],
                        "score": round(r["score"], 4),
                        "evidence": [f"voiceprint_match:{r['id']}"],
                    })
        else:
            # Fallback: brute-force cosine (v1)
            import math

            def cosine(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b))
                na = math.sqrt(sum(x * x for x in a))
                nb = math.sqrt(sum(x * x for x in b))
                if na == 0 or nb == 0:
                    return 0.0
                return dot / (na * nb)

            candidates = []
            for uid, embeddings in self._vpids.items():
                best_score = max(cosine(embedding, e) for e in embeddings) if embeddings else 0.0
                if best_score >= threshold_ambiguous:
                    candidates.append({
                        "uid": uid,
                        "score": round(best_score, 4),
                        "evidence": [f"voiceprint_match:{uid}"],
                    })

        candidates.sort(key=lambda c: c["score"], reverse=True)

        if not candidates:
            return MatchResult(
                query_id="voiceprint",
                decision=MatchDecisionType.NO_MATCH,
                candidates=[],
                requires_review=False,
            )

        best = candidates[0]
        if best["score"] >= threshold_auto and len(candidates) == 1:
            return MatchResult(
                query_id="voiceprint",
                decision=MatchDecisionType.AUTO_MATCH,
                candidates=candidates[:3],
                requires_review=False,
            )
        elif best["score"] >= threshold_auto and len(candidates) > 1:
            return MatchResult(
                query_id="voiceprint",
                decision=MatchDecisionType.AMBIGUOUS,
                candidates=candidates[:5],
                requires_review=True,
                review_reason=f"Multiple candidates above {threshold_auto}: {[c['uid'] for c in candidates[:5]]}",
            )
        else:
            return MatchResult(
                query_id="voiceprint",
                decision=MatchDecisionType.AMBIGUOUS,
                candidates=candidates[:5],
                requires_review=True,
                review_reason=f"Best match {best['score']:.2f} < auto threshold {threshold_auto}",
            )

    # ── List ops ────────────────────────────────────

    def list_nodes(self) -> list[IdentityNode]:
        return list(self._nodes.values())

    def list_bindings(self, active_only: bool = False) -> list[IdentityBinding]:
        if active_only:
            return [b for b in self._bindings.values() if b.is_active]
        return list(self._bindings.values())

    # ── Stats ────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def binding_count(self) -> int:
        return len(self._bindings)

    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for n in self._nodes.values():
            type_counts[n.node_type.value] = type_counts.get(n.node_type.value, 0) + 1
        return {
            "nodes": self.node_count,
            "bindings": self.binding_count,
            "by_type": type_counts,
            "vpid_count": len(self._vpids),
        }

    # ── Persistence ──────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist the graph to a JSON file.

        Format:
          {nodes: [...], bindings: [...], voiceprints: {uid: [[...], ...]}}
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": 2,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [n.model_dump(mode="json") for n in self._nodes.values()],
            "bindings": [b.model_dump(mode="json") for b in self._bindings.values()],
            "voiceprints": {uid: embs for uid, embs in self._vpids.items()},
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("IdentityGraph saved: %d nodes, %d bindings → %s",
                     self.node_count, self.binding_count, path)

    @classmethod
    def load(cls, path: str | Path) -> IdentityGraph:
        """Load a graph from a JSON file.  Returns a fresh IdentityGraph."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Graph file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        graph = cls()

        # Backwards compat: version 1 had flat lists
        version = data.get("version", 1)
        nodes_data = data.get("nodes", data) if version == 1 else data["nodes"]
        bindings_data = data.get("bindings", []) if version >= 2 else []

        for ndata in nodes_data:
            node = IdentityNode(**ndata)
            graph._nodes[node.node_id] = node

        for bdata in bindings_data:
            binding = IdentityBinding(**bdata)
            graph._bindings[binding.binding_id] = binding
            graph._by_source.setdefault(binding.source_id, []).append(binding.binding_id)
            graph._by_target.setdefault(binding.target_id, []).append(binding.binding_id)

        if version >= 2:
            vpids = data.get("voiceprints", {})
            for uid, embs in vpids.items():
                for emb in embs:
                    graph._vpids.setdefault(uid, []).append(emb)

        logger.info("IdentityGraph loaded: %d nodes, %d bindings from %s",
                     graph.node_count, graph.binding_count, path)
        return graph

    def clear(self) -> None:
        """Clear all data.  Useful for testing."""
        self._nodes.clear()
        self._bindings.clear()
        self._by_source.clear()
        self._by_target.clear()
        self._vpids.clear()
        logger.info("IdentityGraph cleared")
