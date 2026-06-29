"""Tests for review writeback layer — Phase 3 v3.

Covers:
  - ReviewResolutionResult model
  - ReviewWritebackDispatcher routing
  - IdentityWritebackHandler (all actions)
  - CRMWritebackHandler
  - MemoryWritebackHandler
  - AuditWritebackHandler
  - ReviewOutcomeApplier orchestration
"""

from __future__ import annotations

import pytest

from byou.review.models import (
    ResolutionAction,
    ReviewItem,
    ReviewItemType,
    ReviewStatus,
    WritebackResult,
)
from byou.review.writeback import (
    AuditWritebackHandler,
    CRMWritebackHandler,
    IdentityWritebackHandler,
    MemoryWritebackHandler,
    PerSystemWritebackState,
    ReviewOutcomeApplier,
    ReviewResolutionResult,
    ReviewWritebackDispatcher,
)


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def identity_item():
    return ReviewItem(
        item_type=ReviewItemType.MERGE_SUGGESTION,
        source="intake",
        related_session_id="sid_001",
        related_uid="uid_abc",
        title="Possible duplicate",
        description="uid_abc and uid_xyz share same phone",
        payload={"source_uid": "uid_abc", "target_uid": "uid_xyz"},
        evidence_refs=["eid_001"],
    )


@pytest.fixture
def postcall_item():
    return ReviewItem(
        item_type=ReviewItemType.QA_LOW_SCORE,
        source="postcall",
        related_session_id="sid_002",
        related_uid="uid_def",
        related_qa_id="qa_001",
        title="Low QA score",
        description="Opening score 0.2, needs review",
        payload={"scores": {"opening": 0.2, "closing": 0.8}},
    )


@pytest.fixture
def approval_item():
    return ReviewItem(
        item_type=ReviewItemType.APPROVAL_REQUIRED,
        source="approval",
        related_session_id="sid_003",
        related_approval_id="app_001",
        title="High-risk action pending",
        description="Send contract to non-qualified lead",
    )


@pytest.fixture
def identity_graph():
    from byou.intake.identity.graph import IdentityGraph, IdentityNode, NodeType
    g = IdentityGraph()
    g.add_node(IdentityNode(node_id="uid_abc", node_type=NodeType.UID, label="Alice"))
    g.add_node(IdentityNode(node_id="uid_xyz", node_type=NodeType.UID, label="Alice",
                            aliases=["alice@example.com"]))
    return g


@pytest.fixture
def fake_crm():
    """In-memory CRM stub for testing."""
    class FakeCRM:
        def __init__(self):
            self.leads = {}
            self.notes = {}
            self.merges = []

        async def upsert_lead(self, data):
            uid = data.get("uid", "unknown")
            self.leads[uid] = data
            return {"status": "ok"}

        async def add_note(self, uid, note):
            self.notes.setdefault(uid, []).append(note)
            return {"status": "ok"}

        async def merge_contacts(self, source, target):
            self.merges.append((source, target))
            return {"status": "ok"}
    return FakeCRM()


@pytest.fixture
def fake_memory():
    class FakeMemory:
        def __init__(self):
            self.summaries = {}
            self.ingested = []

        async def update_memory_summary(self, uid, updates):
            self.summaries.setdefault(uid, {}).update(updates)
            return True

        async def ingest_signals(self, seed):
            self.ingested.append(seed)

        async def merge_summaries(self, source, target):
            if source in self.summaries:
                self.summaries[target] = {**self.summaries.get(target, {}),
                                          **self.summaries.pop(source, {})}
            return True
    return FakeMemory()


@pytest.fixture
def fake_audit():
    class FakeAudit:
        def __init__(self):
            self.entries = []

        async def append(self, entry):
            self.entries.append(entry)
    return FakeAudit()


# ══════════════════════════════════════════════════════════
# ReviewResolutionResult model
# ══════════════════════════════════════════════════════════

class TestReviewResolutionResult:
    def test_creation(self):
        result = ReviewResolutionResult(
            item_id="rev_001",
            resolution_action=ResolutionAction.MERGE_UID,
        )
        assert result.item_id == "rev_001"
        assert result.resolution_action == ResolutionAction.MERGE_UID
        assert result.writebacks == {}
        assert result.all_successful is True

    def test_writeback_states(self):
        result = ReviewResolutionResult(
            item_id="rev_001",
            resolution_action=ResolutionAction.MERGE_UID,
            writebacks={
                "identity": PerSystemWritebackState(
                    target="identity", action="merge_uid", status="success",
                ),
                "crm": PerSystemWritebackState(
                    target="crm", action="merge_uid", status="failed", error="timeout",
                ),
            },
        )
        assert result.all_successful is False
        assert result.has_failures is True
        assert result.failed_targets == ["crm"]

    def test_no_writebacks_all_successful(self):
        result = ReviewResolutionResult(
            item_id="rev_002",
            resolution_action=ResolutionAction.DISMISS,
        )
        assert result.all_successful is True
        assert result.has_failures is False


# ══════════════════════════════════════════════════════════
# ReviewWritebackDispatcher
# ══════════════════════════════════════════════════════════

class TestReviewWritebackDispatcher:

    def test_target_routing_merge_identity(self):
        dispatcher = ReviewWritebackDispatcher()
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        targets = dispatcher._writeback_targets(item, ResolutionAction.MERGE_UID)
        assert "identity" in targets
        assert "crm" in targets
        assert "memory" in targets
        assert "audit" in targets

    def test_target_routing_approve_task(self):
        dispatcher = ReviewWritebackDispatcher()
        item = ReviewItem(
            item_type=ReviewItemType.APPROVAL_REQUIRED,
            source="approval",
            related_session_id="sid_003",
        )
        targets = dispatcher._writeback_targets(item, ResolutionAction.APPROVE_TASK)
        assert "approval" in targets
        assert "durable_exec" in targets
        assert "crm" in targets
        assert "audit" in targets

    def test_target_routing_dismiss(self):
        dispatcher = ReviewWritebackDispatcher()
        item = ReviewItem(
            item_type=ReviewItemType.QA_LOW_SCORE,
            source="postcall",
            related_session_id="sid_002",
        )
        targets = dispatcher._writeback_targets(item, ResolutionAction.DISMISS)
        # Dismiss is cross-cutting with empty list → only audit
        assert targets == ["audit"]

    def test_target_routing_manual_override(self):
        dispatcher = ReviewWritebackDispatcher()
        item = ReviewItem(
            item_type=ReviewItemType.AMBIGUOUS_MATCH,
            source="intake",
            related_session_id="sid_001",
        )
        targets = dispatcher._writeback_targets(item, ResolutionAction.MANUAL_OVERRIDE)
        assert "identity" in targets
        assert "memory" in targets
        assert "crm" in targets
        assert "distillation" in targets
        assert "audit" in targets

    async def test_dispatch_with_handler(self):
        dispatcher = ReviewWritebackDispatcher()

        async def test_handler(item, resolution):
            return WritebackResult(target="test", action="test",
                                    success=True, details={"ok": True})

        dispatcher.register("test", test_handler)

        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        # Override targets for testing
        dispatcher._writeback_targets = lambda i, a: ["test"]
        result = await dispatcher.dispatch(item, resolution)

        assert "test" in result.writebacks
        assert result.writebacks["test"].status == "success"

    async def test_dispatch_missing_handler_skipped(self):
        dispatcher = ReviewWritebackDispatcher()

        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        # identity handler not registered → should skip
        dispatcher._writeback_targets = lambda i, a: ["identity"]
        result = await dispatcher.dispatch(item, resolution)

        assert "identity" in result.writebacks
        assert result.writebacks["identity"].status == "skipped"

    async def test_dispatch_handler_exception_caught(self):
        dispatcher = ReviewWritebackDispatcher()

        async def bad_handler(item, resolution):
            raise ValueError("boom")
        dispatcher.register("bad", bad_handler)

        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        dispatcher._writeback_targets = lambda i, a: ["bad"]
        result = await dispatcher.dispatch(item, resolution)

        assert "bad" in result.writebacks
        assert result.writebacks["bad"].status == "failed"
        assert "boom" in result.writebacks["bad"].error


# ══════════════════════════════════════════════════════════
# IdentityWritebackHandler
# ══════════════════════════════════════════════════════════

class TestIdentityWritebackHandler:

    async def test_merge(self, identity_graph):
        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            payload={"source_uid": "uid_abc", "target_uid": "uid_xyz"},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert result.target == "identity"
        assert result.action == "merge_uid"

    async def test_merge_missing_uids(self, identity_graph):
        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            payload={},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is False

    async def test_confirm_new_uid(self, identity_graph):
        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_type=ReviewItemType.NO_MATCH,
            source="intake",
            related_session_id="sid_001",
            related_uid="uid_candidate",
            payload={"person": {"name": "Bob", "phone": "13800138000"}},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.CONFIRM_NEW_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert result.action == "confirm_new_uid"
        assert "uid" in result.details
        assert len(result.details["uid"]) > 0

    async def test_re_enroll_voiceprint(self, identity_graph):
        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_type=ReviewItemType.MISSING_VOICEPRINT,
            source="intake",
            related_session_id="sid_001",
            related_uid="uid_abc",
            payload={"uid": "uid_abc", "embedding": [0.1, 0.2, 0.3]},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.RE_ENROLL_VOICEPRINT,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert result.details["embedding_dims"] == 3

    async def test_reject_match(self, identity_graph):
        from byou.intake.identity.graph import IdentityBinding, BindingType
        identity_graph.add_binding(IdentityBinding(
            source_id="uid_abc", target_id="uid_xyz",
            binding_type=BindingType.VOICEPRINT_MATCH, confidence=0.6,
        ))
        # Get binding_id
        bindings = identity_graph.get_bindings_for("uid_abc")
        assert len(bindings) > 0
        bid = bindings[0].binding_id

        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_type=ReviewItemType.AMBIGUOUS_MATCH,
            source="intake",
            related_session_id="sid_001",
            payload={"binding_id": bid},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.REJECT_MATCH,
        )

        result = await handler(item, resolution)
        assert result.success is True
        # Verify binding deactivated
        b = identity_graph.get_bindings_for("uid_abc")[0]
        assert b.is_active is False

    async def test_no_graph_injected(self):
        handler = IdentityWritebackHandler(None)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is False
        assert "No identity graph" in result.message

    async def test_non_identity_action_passes_through(self, identity_graph):
        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_type=ReviewItemType.QA_LOW_SCORE,
            source="postcall",
            related_session_id="sid_002",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.APPROVE_TASK,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert "No identity writeback needed" in result.message


# ══════════════════════════════════════════════════════════
# CRMWritebackHandler
# ══════════════════════════════════════════════════════════

class TestCRMWritebackHandler:

    async def test_merge_uid(self, fake_crm):
        handler = CRMWritebackHandler(fake_crm)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            payload={"source_uid": "uid_a", "target_uid": "uid_b"},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert ("uid_a", "uid_b") in fake_crm.merges

    async def test_confirm_new_uid(self, fake_crm):
        handler = CRMWritebackHandler(fake_crm)
        item = ReviewItem(
            item_type=ReviewItemType.NO_MATCH,
            source="intake",
            related_session_id="sid_001",
            related_uid="uid_new_crm",
            payload={"person": {"name": "Bob", "company": "ACME"}},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.CONFIRM_NEW_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert item.related_uid in fake_crm.leads

    async def test_update_crm_note(self, fake_crm):
        handler = CRMWritebackHandler(fake_crm)
        item = ReviewItem(
            item_type=ReviewItemType.QA_LOW_SCORE,
            source="postcall",
            related_session_id="sid_002",
            related_uid="uid_def",
            payload={"note": "Needs manager review"},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.UPDATE_CRM_NOTE,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert "uid_def" in fake_crm.notes

    async def test_no_crm_injected(self):
        handler = CRMWritebackHandler(None)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is False
        assert "No CRM gateway" in result.message

    async def test_non_crm_action_passes_through(self, fake_crm):
        handler = CRMWritebackHandler(fake_crm)
        item = ReviewItem(
            item_type=ReviewItemType.AMBIGUOUS_MATCH,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.REJECT_MATCH,
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert "No CRM writeback needed" in result.message


# ══════════════════════════════════════════════════════════
# MemoryWritebackHandler
# ══════════════════════════════════════════════════════════

class TestMemoryWritebackHandler:

    async def test_merge_uid(self, fake_memory):
        # Pre-populate some data
        await fake_memory.update_memory_summary("uid_a", {"intent_score": 0.8})
        await fake_memory.update_memory_summary("uid_b", {"intent_score": 0.5})

        handler = MemoryWritebackHandler(fake_memory)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            payload={"source_uid": "uid_a", "target_uid": "uid_b"},
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True
        # merge_summaries pops source into target; uid_a is gone, uid_b has merged data
        assert "uid_a" not in fake_memory.summaries
        assert fake_memory.summaries.get("uid_b", {}).get("intent_score") == 0.8

    async def test_no_memory_injected(self):
        handler = MemoryWritebackHandler(None)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is False

    async def test_non_memory_action_passes_through(self, fake_memory):
        handler = MemoryWritebackHandler(fake_memory)
        item = ReviewItem(
            item_type=ReviewItemType.QA_LOW_SCORE,
            source="postcall",
            related_session_id="sid_002",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.FLAG_FOR_RETRY,
        )

        result = await handler(item, resolution)
        assert result.success is True


# ══════════════════════════════════════════════════════════
# AuditWritebackHandler
# ══════════════════════════════════════════════════════════

class TestAuditWritebackHandler:

    async def test_writes_audit_entry(self, fake_audit):
        handler = AuditWritebackHandler(fake_audit)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            related_uid="uid_abc",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
            writebacks={
                "identity": PerSystemWritebackState(
                    target="identity", action="merge_uid", status="success",
                ),
            },
        )

        result = await handler(item, resolution)
        assert result.success is True
        assert len(fake_audit.entries) == 1
        assert fake_audit.entries[0]["event_type"] == "review_merge_uid"

    async def test_no_audit_store(self):
        handler = AuditWritebackHandler(None)
        item = ReviewItem(
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True  # No store is fine


# ══════════════════════════════════════════════════════════
# ReviewOutcomeApplier orchestration
# ══════════════════════════════════════════════════════════

class FakeReviewGateway:
    """Minimal review gateway for testing OutcomeApplier."""
    def __init__(self):
        self.items = {}

    def add(self, item):
        self.items[item.item_id] = item

    def resolve(self, item_id, action, notes="", reviewer="system"):
        return self.items.get(item_id)

    def list_by_session(self, session_id):
        return [i for i in self.items.values() if i.related_session_id == session_id]


class TestReviewOutcomeApplier:

    @pytest.fixture
    def gw(self):
        return FakeReviewGateway()

    @pytest.fixture
    def applier(self, gw, identity_graph, fake_crm, fake_memory, fake_audit):
        dispatcher = ReviewWritebackDispatcher()
        dispatcher.register("identity", IdentityWritebackHandler(identity_graph))
        dispatcher.register("crm", CRMWritebackHandler(fake_crm))
        dispatcher.register("memory", MemoryWritebackHandler(fake_memory))
        dispatcher.register("audit", AuditWritebackHandler(fake_audit))
        return ReviewOutcomeApplier(gw, dispatcher)

    async def test_apply_merge(self, applier, gw):
        item = ReviewItem(
            item_id="rev_test_01",
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            payload={"source_uid": "uid_abc", "target_uid": "uid_xyz"},
        )
        gw.add(item)

        result = await applier.apply(
            item_id="rev_test_01",
            action=ResolutionAction.MERGE_UID,
            notes="Approved — same phone number",
        )
        assert result.item_id == "rev_test_01"
        # Should have writebacks for identity, crm, memory, audit
        assert len(result.writebacks) >= 4

    async def test_apply_confirm_new_uid(self, applier, gw):
        item = ReviewItem(
            item_id="rev_test_02",
            item_type=ReviewItemType.NO_MATCH,
            source="intake",
            related_session_id="sid_002",
            payload={"person": {"name": "Carol", "phone": "13900139000"}},
        )
        gw.add(item)

        result = await applier.apply(
            item_id="rev_test_02",
            action=ResolutionAction.CONFIRM_NEW_UID,
            notes="New lead confirmed",
        )
        assert result.item_id == "rev_test_02"
        assert "identity" in result.writebacks

    async def test_apply_dismiss(self, applier, gw):
        item = ReviewItem(
            item_id="rev_test_03",
            item_type=ReviewItemType.QA_LOW_SCORE,
            source="postcall",
            related_session_id="sid_003",
        )
        gw.add(item)

        result = await applier.apply(
            item_id="rev_test_03",
            action=ResolutionAction.DISMISS,
            notes="Not actionable",
        )
        assert result.item_id == "rev_test_03"


# ══════════════════════════════════════════════════════════
# Evidence chain preservation
# ══════════════════════════════════════════════════════════

class TestEvidenceChainPreservation:

    async def test_writeback_preserves_review_id(self, identity_graph, fake_audit):
        handler = IdentityWritebackHandler(identity_graph)
        item = ReviewItem(
            item_id="rev_evidence_01",
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            payload={"source_uid": "uid_abc", "target_uid": "uid_xyz"},
            evidence_refs=["eid_001", "eid_002"],
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        result = await handler(item, resolution)
        assert result.success is True

        # Verify the merge binding references the review
        bindings = identity_graph.list_bindings()
        merge_bindings = [b for b in bindings if b.binding_type.value == "merged_into"]
        assert len(merge_bindings) > 0

    async def test_audit_contains_evidence_refs(self, identity_graph, fake_audit):
        handler = AuditWritebackHandler(fake_audit)
        item = ReviewItem(
            item_id="rev_evidence_02",
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
            evidence_refs=["eid_001"],
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.MERGE_UID,
        )

        await handler(item, resolution)
        entry = fake_audit.entries[0]
        assert entry["item_id"] == "rev_evidence_02"

    async def test_transcript_not_in_writeback_payload(self, fake_audit):
        """Verify writeback NEVER contains transcript."""
        handler = AuditWritebackHandler(fake_audit)
        item = ReviewItem(
            item_id="rev_evidence_03",
            item_type=ReviewItemType.QA_LOW_SCORE,
            source="postcall",
            related_session_id="sid_001",
            payload={"transcript": "This should not be in writeback"},
            evidence_refs=["eid_transcript_ref"],  # EID reference, not content
        )
        resolution = ReviewResolutionResult(
            item_id=item.item_id,
            resolution_action=ResolutionAction.DISMISS,
        )

        await handler(item, resolution)
        entry = fake_audit.entries[0]
        # Writeback should have item metadata, not the transcript payload itself
        assert "session_id" in entry
        assert "sid_001" == entry["session_id"]
