# byou/intake/identity/writeback.py
"""Identity Graph Writeback & Replay — Phase 3 v3.

Identity graph ↔ review ↔ replay closed loop:
  - IdentityWriteback: review resolution → graph update (merge, confirm, reject, enroll, override)
  - IdentityMergeResult: full merge outcome with snapshots & audit trail
  - IdentityBindingUpdate: per-binding change record for audit
  - IdentityReplaySnapshot: point-in-time graph snapshot for replay
  - IdentityParticipantBinder: bind resolved identities to session participants
  - IdentityCascade: downstream updates after identity merge (memory, crm, review, audit)
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from byou.intake.identity.graph import (
    BindingType,
    IdentityBinding,
    IdentityGraph,
    IdentityNode,
    MatchDecisionType,
    NodeType,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════

class IdentityBindingUpdate(BaseModel):
    """Per-binding change record for audit trail."""
    binding_id: str
    source_id: str
    target_id: str
    binding_type: BindingType
    old_state: dict[str, Any] = Field(default_factory=dict)
    new_state: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    changed_by: str = "review"
    review_item_id: str = ""
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IdentityMergeResult(BaseModel):
    """Full merge outcome with pre/post snapshots and audit trail."""
    merge_id: str = Field(default_factory=lambda: f"merge_{uuid4().hex[:8]}")
    source_uid: str
    target_uid: str
    success: bool = False
    bindings_migrated: int = 0
    aliases_merged: list[str] = Field(default_factory=list)
    pre_merge_snapshot: dict[str, Any] = Field(default_factory=dict)
    post_merge_snapshot: dict[str, Any] = Field(default_factory=dict)
    binding_updates: list[IdentityBindingUpdate] = Field(default_factory=list)
    review_item_id: str = ""
    resolved_by: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_reversible(self) -> bool:
        return bool(self.pre_merge_snapshot)


class IdentityReplaySnapshot(BaseModel):
    """Point-in-time graph snapshot for replay.

    Captures nodes, bindings, and voiceprints.  Can be restored
    to a fresh IdentityGraph for replay scenarios.
    """
    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid4().hex[:8]}")
    session_id: str = ""
    taken_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    bindings: list[dict[str, Any]] = Field(default_factory=list)
    voiceprints: dict[str, list[list[float]]] = Field(default_factory=dict)

    node_count: int = 0
    binding_count: int = 0
    uid_count: int = 0
    vpid_count: int = 0

    def to_graph(self) -> IdentityGraph:
        """Restore a fresh IdentityGraph from this snapshot."""
        g = IdentityGraph()
        for ndata in self.nodes:
            node = IdentityNode(**ndata)
            g.add_node(node)
        for bdata in self.bindings:
            binding = IdentityBinding(**bdata)
            g.add_binding(binding)
        for uid, embs in self.voiceprints.items():
            for emb in embs:
                g.register_voiceprint(uid, emb)
        return g


# ══════════════════════════════════════════════════════════
# IdentityWriteback
# ══════════════════════════════════════════════════════════

class IdentityWriteback:
    """Write review resolutions back to the identity graph.

    All mutations are tracked with:
      - audit trail (review_item_id)
      - pre/post snapshots (for merge)
      - merge history (for rollback)

    Usage:
        iw = IdentityWriteback(graph)
        result = await iw.apply_review_merge("uid_src", "uid_tgt", "rev_001")
    """

    def __init__(self, identity_graph: IdentityGraph):
        self._graph = identity_graph
        self._merge_history: list[IdentityMergeResult] = []

    # ── Review operations ───────────────────────────────

    async def apply_review_merge(
        self, source_uid: str, target_uid: str, review_item_id: str = "",
        resolved_by: str = "",
    ) -> IdentityMergeResult:
        """Merge source_uid into target_uid, preserving evidence chain."""
        result = IdentityMergeResult(
            source_uid=source_uid,
            target_uid=target_uid,
            review_item_id=review_item_id,
            resolved_by=resolved_by,
        )

        source_node = self._graph.get_node(source_uid)
        target_node = self._graph.get_node(target_uid)

        if not source_node or not target_node:
            result.success = False
            return result

        # Snapshot before
        result.pre_merge_snapshot = self._snapshot_dict()

        # Create MERGED_INTO binding
        binding = IdentityBinding(
            source_id=source_uid,
            target_id=target_uid,
            binding_type=BindingType.MERGED_INTO,
            confidence=1.0,
            evidence_refs=[review_item_id],
            metadata={"resolved_by": resolved_by},
        )
        self._graph.add_binding(binding)

        # Deactivate old bindings on source
        old_bindings = self._graph.get_bindings_for(source_uid)
        alias_count = 0
        for b in old_bindings:
            if b.is_active and b.binding_type != BindingType.MERGED_INTO:
                old_state = {
                    "is_active": True,
                    "confidence": b.confidence,
                    "binding_type": b.binding_type.value,
                }
                b.is_active = False
                update = IdentityBindingUpdate(
                    binding_id=b.binding_id,
                    source_id=b.source_id,
                    target_id=b.target_id,
                    binding_type=b.binding_type,
                    old_state=old_state,
                    new_state={
                        "is_active": False,
                        "confidence": b.confidence,
                        "binding_type": b.binding_type.value,
                    },
                    changed_fields=["is_active"],
                    review_item_id=review_item_id,
                )
                result.binding_updates.append(update)
                result.bindings_migrated += 1

        # Migrate aliases
        for alias in source_node.aliases:
            if alias not in target_node.aliases:
                target_node.aliases.append(alias)
                alias_count += 1
        target_node.aliases.append(source_node.label)
        alias_count += 1
        result.aliases_merged = [source_node.label] + source_node.aliases

        # Migrate voiceprints
        vps = self._graph.get_voiceprints(source_uid)
        for emb in vps:
            self._graph.register_voiceprint(target_uid, emb)

        # Snapshot after
        result.post_merge_snapshot = self._snapshot_dict()
        result.success = True

        self._merge_history.append(result)
        return result

    async def apply_review_confirm(
        self, person: dict[str, Any], uid: str = "",
        related_vpid: str = "", review_item_id: str = "",
    ) -> dict[str, Any]:
        """Confirm a new UID from review."""
        if not uid:
            uid = f"uid_rev_{uuid4().hex[:8]}"

        name = person.get("name", uid)
        node = IdentityNode(
            node_id=uid,
            node_type=NodeType.UID,
            label=name,
            aliases=[v for v in person.values() if isinstance(v, str) and v and len(v) > 1],
            metadata={
                "phone": person.get("phone", ""),
                "email": person.get("email", ""),
                "company": person.get("company", ""),
                "title": person.get("title", ""),
                "confirmed_by": "review",
                "review_id": review_item_id,
            },
        )
        self._graph.add_node(node)

        binding_id = ""
        if related_vpid:
            binding = IdentityBinding(
                source_id=related_vpid,
                target_id=uid,
                binding_type=BindingType.VOICEPRINT_MATCH,
                confidence=0.9,
                evidence_refs=[review_item_id],
                metadata={"confirmed_by": "review"},
            )
            self._graph.add_binding(binding)
            binding_id = binding.binding_id

        return {"uid": uid, "name": name, "binding_id": binding_id}

    async def apply_review_reject(
        self, binding_id: str, review_item_id: str = "",
    ) -> dict[str, Any]:
        """Reject a binding (deactivate it)."""
        self._graph.deactivate_binding(binding_id)
        return {"deactivated": binding_id, "review_item_id": review_item_id}

    async def apply_review_enroll(
        self, uid: str, embedding: list[float],
        review_item_id: str = "",
    ) -> dict[str, Any]:
        """Re-enroll a voiceprint for a UID."""
        self._graph.register_voiceprint(uid, embedding)
        return {
            "uid": uid,
            "embedding_dims": len(embedding),
            "review_item_id": review_item_id,
        }

    async def apply_review_manual_override(
        self, uid: str, overrides: dict[str, Any],
        review_item_id: str = "",
    ) -> dict[str, Any]:
        """Apply manual overrides to a UID node."""
        node = self._graph.get_node(uid)
        if not node:
            return {}

        changed = []
        for key, val in overrides.items():
            if key == "label":
                node.label = val
                changed.append("label")
            elif key == "aliases" and isinstance(val, list):
                for a in val:
                    if a not in node.aliases:
                        node.aliases.append(a)
                changed.append(f"aliases:+{len(val)}")
            elif key in ("phone", "email", "company", "title"):
                if node.metadata.get(key) != val:
                    node.metadata[key] = val
                    changed.append(key)

        return {"uid": uid, "changed": changed, "review_item_id": review_item_id}

    # ── Snapshot ────────────────────────────────────────

    def take_snapshot(self, session_id: str = "") -> IdentityReplaySnapshot:
        """Take a point-in-time snapshot for replay."""
        snap = IdentityReplaySnapshot(session_id=session_id)

        for node in self._graph.list_nodes():
            snap.nodes.append(node.model_dump(mode="json"))

        uid_count = 0
        for b in self._graph.list_bindings():
            snap.bindings.append(b.model_dump(mode="json"))

        for node in self._graph.list_nodes():
            if node.node_type == NodeType.UID:
                uid_count += 1

        snap.node_count = len(snap.nodes)
        snap.binding_count = len(snap.bindings)
        snap.uid_count = uid_count
        snap.vpid_count = snapshot_vpid_count = self._graph.stats().get("vpid_count", 0)

        # Deep copy voiceprints
        vpids_copy: dict[str, list[list[float]]] = {}
        for node in self._graph.list_nodes():
            if node.node_type == NodeType.UID:
                vps = self._graph.get_voiceprints(node.node_id)
                if vps:
                    vpids_copy[node.node_id] = [list(e) for e in vps]
        snap.voiceprints = vpids_copy

        return snap

    # ── Helpers ─────────────────────────────────────────

    def _snapshot_dict(self) -> dict[str, Any]:
        return {
            "node_count": self._graph.node_count,
            "binding_count": self._graph.binding_count,
            "nodes": {n.node_id: n.label for n in self._graph.list_nodes()},
            "stats": self._graph.stats(),
        }

    @property
    def merge_history(self) -> list[IdentityMergeResult]:
        return list(self._merge_history)

    def get_last_merge(self, source_uid: str) -> IdentityMergeResult | None:
        for m in reversed(self._merge_history):
            if m.source_uid == source_uid:
                return m
        return None


# ══════════════════════════════════════════════════════════
# IdentityParticipantBinder
# ══════════════════════════════════════════════════════════

class IdentityParticipantBinder:
    """Bind session participants to known identities in the graph.

    Post-review, resolved identities should flow back into participant binding.
    This is the bridge between identity graph and session-level participants.
    """

    def __init__(self, identity_graph: IdentityGraph):
        self._graph = identity_graph

    def bind_participant(self, participant: dict[str, Any]) -> dict[str, Any]:
        """Bind one participant to a known identity.

        Returns enriched participant dict with identity_ref and confidence.
        """
        result = {**participant, "identity_ref": "", "identity_confidence": 0.0,
                  "identity_status": "unknown"}

        # Check by direct identity_ref
        id_ref = participant.get("identity_ref", "")
        if id_ref:
            merged_to = self._find_merged_target(id_ref)
            effective_uid = merged_to or id_ref
            node = self._graph.get_node(effective_uid)
            if node and node.node_type == NodeType.UID:
                result["identity_ref"] = effective_uid
                result["identity_confidence"] = 1.0
                result["identity_status"] = "confirmed"
                return result

        # Check by phone
        phone = participant.get("phone", "")
        if phone:
            for node in self._graph.list_nodes():
                if node.node_type == NodeType.UID and node.metadata.get("phone") == phone:
                    result["identity_ref"] = node.node_id
                    result["identity_confidence"] = 0.95
                    result["identity_status"] = "confirmed"
                    return result

        # Check by display_name
        name = participant.get("display_name", "")
        if name:
            matches = self._graph.find_by_alias(name)
            if matches:
                best = matches[0]
                # Check if merged
                merged_to = self._find_merged_target(best.node_id)
                result["identity_ref"] = merged_to or best.node_id
                result["identity_confidence"] = 0.7
                result["identity_status"] = (
                    "confirmed" if merged_to else "potential"
                )
                result["identity_candidates"] = [m.node_id for m in matches[:3]]
                return result

        return result

    def bind_all_participants(
        self, participants: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Bind all participants in a batch."""
        return [self.bind_participant(p) for p in participants]

    def _find_merged_target(self, uid: str) -> str:
        """If this UID was merged into another, return the target."""
        for b in self._graph.list_bindings():
            if (b.source_id == uid and
                b.binding_type == BindingType.MERGED_INTO and
                    b.is_active):
                return b.target_id
        return ""


# ══════════════════════════════════════════════════════════
# IdentityCascade
# ══════════════════════════════════════════════════════════

class IdentityCascade:
    """Post-merge cascade: propagate identity merge to all downstream systems.

    After identity merge (uid_a → uid_b), cascade:
      - Memory: merge_summaries(uid_a, uid_b)
      - CRM: merge_contacts(uid_a, uid_b)
      - Review: repoint_uid(uid_a, uid_b) on pending review items
      - Audit: log merge event

    All gateways optional — graceful degrade.
    """

    def __init__(
        self,
        memory_gateway: Any = None,
        crm_gateway: Any = None,
        review_gateway: Any = None,
        audit_store: Any = None,
    ):
        self._memory = memory_gateway
        self._crm = crm_gateway
        self._review = review_gateway
        self._audit = audit_store

    async def cascade_merge(
        self, merge_result: IdentityMergeResult, dry_run: bool = False,
    ) -> dict[str, Any]:
        """Propagate a completed merge to all downstream systems."""
        source = merge_result.source_uid
        target = merge_result.target_uid
        merge_id = merge_result.merge_id
        csc_results: dict[str, Any] = {}

        # ── Memory ──
        if self._memory:
            if not dry_run and hasattr(self._memory, "merge_summaries"):
                try:
                    await self._memory.merge_summaries(source, target)
                    csc_results["memory"] = {"status": "ok", "merge_id": merge_id}
                except Exception as e:
                    csc_results["memory"] = {"status": "error", "error": str(e)}
            else:
                csc_results["memory"] = {"status": "ok", "dry_run": True}

        # ── CRM ──
        if self._crm:
            if not dry_run and hasattr(self._crm, "merge_contacts"):
                try:
                    await self._crm.merge_contacts(source, target)
                    csc_results["crm"] = {"status": "ok", "merge_id": merge_id}
                except Exception as e:
                    csc_results["crm"] = {"status": "error", "error": str(e)}
            else:
                csc_results["crm"] = {"status": "ok", "dry_run": True}

        # ── Review repoint ──
        if self._review and hasattr(self._review, "repoint_uid"):
            try:
                await self._review.repoint_uid(source, target)
                csc_results["review"] = {"status": "ok"}
            except Exception as e:
                csc_results["review"] = {"status": "error", "error": str(e)}

        # ── Audit ──
        if self._audit:
            try:
                entry = {
                    "event_type": "identity_merged",
                    "merge_id": merge_id,
                    "source_uid": source,
                    "target_uid": target,
                    "bindings_migrated": merge_result.bindings_migrated,
                    "review_item_id": merge_result.review_item_id,
                    "resolved_by": merge_result.resolved_by,
                }
                if hasattr(self._audit, "append"):
                    await self._audit.append(entry)
                csc_results["audit"] = {"status": "ok"}
            except Exception as e:
                csc_results["audit"] = {"status": "error", "error": str(e)}

        return csc_results
