"""Tests for identity graph ↔ review linkage — Phase 3 v3.

Covers:
  - IdentityWriteback (review → graph)
  - IdentityReplaySnapshot (snapshot → replay)
  - IdentityParticipantBinder (graph → participant)
  - IdentityCascade (merge → downstream)
  - IdentityMergeResult full model
  - IdentityBindingUpdate per-binding change
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from byou.intake.identity.graph import (
    BindingType,
    IdentityBinding,
    IdentityGraph,
    IdentityNode,
    MatchDecisionType,
    MatchResult,
    NodeType,
)
from byou.intake.identity.merger import IdentityMerger
from byou.intake.identity.writeback import (
    IdentityBindingUpdate,
    IdentityCascade,
    IdentityMergeResult,
    IdentityParticipantBinder,
    IdentityReplaySnapshot,
    IdentityWriteback,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def graph():
    g = IdentityGraph()
    g.add_node(IdentityNode(node_id="uid_alice", node_type=NodeType.UID,
                            label="Alice Wang", aliases=["alice@example.com"],
                            metadata={"phone": "13900139000", "company": "ACME", "title": "CTO"}))
    g.add_node(IdentityNode(node_id="uid_alice_dup", node_type=NodeType.UID,
                            label="Alice", aliases=["alice_wang"],
                            metadata={"phone": "13900139000", "company": "ACME"}))
    g.add_node(IdentityNode(node_id="uid_bob", node_type=NodeType.UID,
                            label="Bob Li", metadata={"phone": "13800138000", "company": "Beta Inc"}))
    g.add_node(IdentityNode(node_id="vpid_001", node_type=NodeType.VPID,
                            label="voiceprint_alice"))
    g.register_voiceprint("uid_alice", [0.1, 0.2, 0.3, 0.4])
    g.register_voiceprint("uid_bob", [0.5, 0.6, 0.7, 0.8])

    # Create an ambiguous binding for testing
    g.add_binding(IdentityBinding(
        source_id="vpid_001", target_id="uid_alice",
        binding_type=BindingType.VOICEPRINT_MATCH, confidence=0.72,
        evidence_refs=["eid_001"],
    ))
    return g


@pytest.fixture
def iwb(graph):
    return IdentityWriteback(graph)


# ══════════════════════════════════════════════════════════
# IdentityMergeResult model
# ══════════════════════════════════════════════════════════

class TestIdentityMergeResult:
    def test_creation(self):
        result = IdentityMergeResult(
            source_uid="uid_a",
            target_uid="uid_b",
            success=True,
            bindings_migrated=3,
            aliases_merged=["alice@old.com"],
            pre_merge_snapshot={"node_count": 10},
            post_merge_snapshot={"node_count": 9},
        )
        assert result.success is True
        assert result.bindings_migrated == 3
        assert result.is_reversible is True

    def test_audit_info(self):
        result = IdentityMergeResult(
            source_uid="uid_a", target_uid="uid_b",
            review_item_id="rev_001",
            resolved_by="human_reviewer",
        )
        assert result.review_item_id == "rev_001"
        assert result.resolved_by == "human_reviewer"


# ══════════════════════════════════════════════════════════
# IdentityBindingUpdate model
# ══════════════════════════════════════════════════════════

class TestIdentityBindingUpdate:
    def test_creation(self):
        update = IdentityBindingUpdate(
            binding_id="bind_001",
            source_id="uid_a",
            target_id="uid_b",
            binding_type=BindingType.VOICEPRINT_MATCH,
            old_state={"confidence": 0.6, "is_active": True},
            new_state={"confidence": 1.0, "is_active": True},
            changed_fields=["confidence"],
            review_item_id="rev_001",
        )
        assert update.changed_fields == ["confidence"]
        assert update.changed_by == "review"


# ══════════════════════════════════════════════════════════
# IdentityWriteback — review → graph
# ══════════════════════════════════════════════════════════

class TestIdentityWriteback:

    # ── apply_review_merge ──

    async def test_merge_uids(self, graph, iwb):
        result = await iwb.apply_review_merge(
            source_uid="uid_alice_dup",
            target_uid="uid_alice",
            review_item_id="rev_merge_001",
        )
        assert result.success is True
        assert result.bindings_migrated >= 0
        assert result.review_item_id == "rev_merge_001"

    async def test_merge_preserves_evidence_chain(self, graph, iwb):
        result = await iwb.apply_review_merge(
            source_uid="uid_alice_dup",
            target_uid="uid_alice",
            review_item_id="rev_evidence_001",
        )
        assert result.success is True
        # Check MERGED_INTO binding exists
        bindings = graph.list_bindings()
        merge_bindings = [b for b in bindings if b.binding_type == BindingType.MERGED_INTO]
        assert len(merge_bindings) >= 1

    async def test_merge_history_tracked(self, iwb):
        result = await iwb.apply_review_merge("uid_alice_dup", "uid_alice", "rev_002")
        assert len(iwb.merge_history) >= 1
        assert iwb.merge_history[0].merge_id == result.merge_id

    # ── apply_review_confirm ──

    async def test_confirm_new_uid(self, graph, iwb):
        person = {"name": "Carol Chen", "phone": "13700137000", "company": "Gamma Corp"}
        result = await iwb.apply_review_confirm(
            person, uid="uid_carol", review_item_id="rev_confirm_001",
        )
        assert "uid_carol" in result["uid"]
        node = graph.get_node("uid_carol")
        assert node is not None
        assert node.label == "Carol Chen"
        assert node.metadata["company"] == "Gamma Corp"

    async def test_confirm_with_voiceprint(self, graph, iwb):
        person = {"name": "Dave", "phone": "13600136000"}
        result = await iwb.apply_review_confirm(
            person, uid="uid_dave", related_vpid="vpid_001",
            review_item_id="rev_confirm_002",
        )
        assert result["binding_id"] != ""  # binding created

    # ── apply_review_reject ──

    async def test_reject_match(self, graph, iwb):
        # Deactivate the ambiguous binding
        bindings = graph.list_bindings()
        assert any(b.is_active for b in bindings)

        result = await iwb.apply_review_reject(
            binding_id=bindings[0].binding_id,
            review_item_id="rev_reject_001",
        )
        assert "deactivated" in result

        bindings = graph.list_bindings()
        assert all(not b.is_active for b in bindings)

    # ── apply_review_enroll ──

    async def test_re_enroll_voiceprint(self, graph, iwb):
        embedding = [0.9, 0.8, 0.7, 0.6]
        result = await iwb.apply_review_enroll(
            "uid_alice", embedding, review_item_id="rev_enroll_001",
        )
        assert result["embedding_dims"] == 4
        vps = graph.get_voiceprints("uid_alice")
        assert len(vps) >= 2  # original + new

    # ── apply_review_manual_override ──

    async def test_manual_override(self, graph, iwb):
        result = await iwb.apply_review_manual_override(
            "uid_alice",
            {"label": "Alice Wang (Verified)", "title": "CTO & Co-founder"},
            review_item_id="rev_override_001",
        )
        assert "label" in result.get("changed", [])
        node = graph.get_node("uid_alice")
        assert node.label == "Alice Wang (Verified)"
        assert node.metadata["title"] == "CTO & Co-founder"

    # ── Snapshot ──

    async def test_take_snapshot(self, graph, iwb):
        snap = iwb.take_snapshot(session_id="sid_001")
        assert snap.node_count >= 4
        assert snap.uid_count >= 3
        assert snap.vpid_count >= 1
        assert len(snap.nodes) == snap.node_count
        assert len(snap.bindings) == snap.binding_count

    async def test_snapshot_restore(self, graph, iwb):
        snap = iwb.take_snapshot(session_id="sid_001")
        restored = snap.to_graph()
        assert restored.node_count == snap.node_count
        assert restored.binding_count == snap.binding_count

    async def test_get_last_merge(self, graph, iwb):
        await iwb.apply_review_merge("uid_alice_dup", "uid_alice", "rev_003")
        last = iwb.get_last_merge("uid_alice_dup")
        assert last is not None
        assert last.source_uid == "uid_alice_dup"
        assert last.target_uid == "uid_alice"


# ══════════════════════════════════════════════════════════
# IdentityParticipantBinder
# ══════════════════════════════════════════════════════════

class TestIdentityParticipantBinder:

    @pytest.fixture
    def binder(self, graph):
        return IdentityParticipantBinder(graph)

    def test_bind_by_phone(self, binder):
        participant = {"display_name": "Alice", "phone": "13900139000"}
        result = binder.bind_participant(participant)
        assert result["identity_status"] == "confirmed"
        assert result["identity_confidence"] == 0.95
        assert "uid_alice" in result["identity_ref"]

    def test_bind_unknown(self, binder):
        participant = {"display_name": "Unknown"}
        result = binder.bind_participant(participant)
        assert result["identity_status"] == "unknown"
        assert result["identity_confidence"] == 0.0

    def test_bind_all(self, binder):
        participants = [
            {"display_name": "Alice", "phone": "13900139000"},
            {"display_name": "Bob", "phone": "13800138000"},
            {"display_name": "Unknown"},
        ]
        results = binder.bind_all_participants(participants)
        assert len(results) == 3
        assert results[0]["identity_status"] == "confirmed"
        assert results[1]["identity_status"] == "confirmed"
        assert results[2]["identity_status"] == "unknown"

    def test_bind_merged_identity(self, graph):
        """After merge, participants with source_uid should resolve to target."""
        # Merge first
        merger = IdentityMerger(graph)
        merger.merge("uid_alice_dup", "uid_alice")

        binder = IdentityParticipantBinder(graph)
        participant = {"display_name": "Alice Dup", "identity_ref": "uid_alice_dup"}
        result = binder.bind_participant(participant)
        # Should resolve to uid_alice
        assert result["identity_status"] == "confirmed"


# ══════════════════════════════════════════════════════════
# IdentityCascade
# ══════════════════════════════════════════════════════════

class FakeMemory:
    def __init__(self):
        self.merges = []
        self.merged_data = {}

    async def merge_summaries(self, source, target):
        self.merges.append((source, target))
        if source in self.merged_data:
            self.merged_data[target] = {**self.merged_data.get(target, {}),
                                        **self.merged_data.pop(source, {})}
        return True


class FakeCRM:
    def __init__(self):
        self.merges = []

    async def merge_contacts(self, source, target):
        self.merges.append((source, target))
        return True


class FakeReview:
    def __init__(self):
        self.repoints = []

    async def repoint_uid(self, source, target):
        self.repoints.append((source, target))
        return True


class FakeAudit:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)
        return True


class TestIdentityCascade:

    @pytest.fixture
    def cascade(self):
        return IdentityCascade(
            memory_gateway=FakeMemory(),
            crm_gateway=FakeCRM(),
            review_gateway=FakeReview(),
            audit_store=FakeAudit(),
        )

    async def test_cascade_merge_full(self, cascade):
        merge_result = IdentityMergeResult(
            source_uid="uid_a", target_uid="uid_b", success=True,
            bindings_migrated=5,
        )
        results = await cascade.cascade_merge(merge_result)
        assert "memory" in results
        assert "crm" in results
        assert "review" in results
        assert "audit" in results

    async def test_cascade_dry_run(self, cascade):
        merge_result = IdentityMergeResult(
            source_uid="uid_a", target_uid="uid_b", success=True,
        )
        results = await cascade.cascade_merge(merge_result, dry_run=True)
        assert results["memory"]["dry_run"] is True
        assert results["crm"]["dry_run"] is True

        # Verify no actual side effects
        assert len(cascade._crm.merges) == 0

    async def test_cascade_no_gateways(self):
        cascade = IdentityCascade(
            memory_gateway=None, crm_gateway=None,
            review_gateway=None, audit_store=None,
        )
        merge_result = IdentityMergeResult(
            source_uid="uid_a", target_uid="uid_b", success=True,
        )
        results = await cascade.cascade_merge(merge_result)
        # All should gracefully degrade
        assert results == {}
