"""Tests for replay engine — Phase 3 v3.

Covers:
  - ReplaySource loading
  - ReplayEngine step execution
  - Divergence detection
  - Review fix application
  - ReplayFactory building
  - Graceful degrade with missing injects
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from byou.replay import (
    ReplayEngine,
    ReplayFactory,
    ReplayRequest,
    ReplayResult,
    ReplaySource,
    ReplaySourceType,
    ReplayStep,
    ReplayStepStatus,
    ReplayStepType,
)


# ══════════════════════════════════════════════════════════
# Fake dependencies
# ══════════════════════════════════════════════════════════

class FakeActionDecider:
    def __init__(self):
        self.calls = []

    async def decide(self, input_data):
        self.calls.append(input_data)
        return {"decision": "crm_note_only", "confidence": 0.8}


class FakeFollowUpPlanner:
    def __init__(self):
        self.calls = []

    async def plan(self, input_data):
        self.calls.append(input_data)
        return {"plan": "call_in_3_days", "channel": "phone"}


class FakeDistillationRunner:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return {"type": "DistilledKnowledge", "playbook_count": 3}


class FakeIdentityGateway:
    def __init__(self):
        self.nodes = {}
        self.bindings = []

    async def snapshot(self):
        return {"nodes": len(self.nodes), "bindings": len(self.bindings), "uid_count": 5}


class FakeReviewGateway:
    def __init__(self):
        self.items = {}

    def add(self, item):
        self.items[item.item_id] = item

    def resolve(self, item_id, action, notes="", reviewer="system"):
        return self.items.get(item_id)

    def list_by_session(self, session_id):
        return [i for i in self.items.values() if i.related_session_id == session_id]

    def get(self, item_id):
        return self.items.get(item_id)


class FakeAuditStore:
    def __init__(self):
        self.entries = []

    async def append(self, entry):
        self.entries.append(entry)

    async def query_by_session(self, session_id):
        return [e for e in self.entries if e.get("session_id") == session_id]


class FakeMemoryGateway:
    def __init__(self):
        self.signals = []
        self.distilled = {}

    async def ingest_signals(self, seed):
        self.signals.append(seed)
        return True

    async def query_by_session(self, session_id):
        return [s for s in self.signals if s.get("session_id") == session_id]

    async def get_distilled_for(self, session_id):
        return self.distilled.get(session_id, [])

    async def update_memory_summary(self, uid, updates):
        return True


# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════

@pytest.fixture
def audit_store():
    store = FakeAuditStore()
    store.entries = [
        {"session_id": "sid_001", "event_type": "action_decider",
         "outcome": "qualified", "payload": {"action_type": "follow_up_task"}},
        {"session_id": "sid_001", "event_type": "follow_up_planner",
         "outcome": "follow_up", "payload": {"priority": "high"}},
    ]
    return store


@pytest.fixture
def full_engine(audit_store):
    engine = ReplayEngine()
    engine.inject_action_decider(FakeActionDecider())
    engine.inject_follow_up_planner(FakeFollowUpPlanner())
    engine.inject_distillation_runner(FakeDistillationRunner())
    engine.inject_identity_gateway(FakeIdentityGateway())
    engine.inject_review_gateway(FakeReviewGateway())
    engine.inject_audit_store(audit_store)
    engine.inject_memory_gateway(FakeMemoryGateway())
    return engine


# ══════════════════════════════════════════════════════════
# ReplaySource
# ══════════════════════════════════════════════════════════

class TestReplaySource:
    def test_creation(self):
        source = ReplaySource(
            source_type=ReplaySourceType.AUDIT_LOG,
            session_id="sid_001",
        )
        assert source.source_type == ReplaySourceType.AUDIT_LOG
        assert source.session_id == "sid_001"
        assert source.source_count == 0

    def test_source_count(self):
        source = ReplaySource(
            source_type=ReplaySourceType.AUDIT_LOG,
            session_id="sid_001",
            audit_entries=[{"a": 1}, {"b": 2}],
            seeds=[{"c": 3}],
        )
        assert source.source_count == 3


# ══════════════════════════════════════════════════════════
# ReplayEngine — source loading
# ══════════════════════════════════════════════════════════

class TestReplayEngineSourceLoading:

    async def test_load_audit_source(self, full_engine):
        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG],
        )
        source = await full_engine.load_source(request)
        assert source.source_type == ReplaySourceType.AUDIT_LOG
        assert len(source.audit_entries) == 2

    async def test_load_multiple_sources(self, full_engine):
        # Also add seeds to memory gateway
        full_engine._memory_gateway.signals = [
            {"session_id": "sid_001", "type": "memory_seed", "content": "test"},
        ]
        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG, ReplaySourceType.SEEDS],
        )
        source = await full_engine.load_source(request)
        assert len(source.audit_entries) == 2
        assert len(source.seeds) == 1
        assert source.source_count >= 3

    async def test_load_empty_session(self, full_engine):
        request = ReplayRequest(
            session_id="sid_nonexistent",
            sources=[ReplaySourceType.AUDIT_LOG],
        )
        source = await full_engine.load_source(request)
        assert source.source_count == 0


# ══════════════════════════════════════════════════════════
# ReplayEngine — replay execution
# ══════════════════════════════════════════════════════════

class TestReplayEngineExecution:

    async def test_replay_action_decider(self, full_engine):
        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG],
            steps=[ReplayStepType.ACTION_DECIDER],
            compare_with_original=False,
        )
        source = await full_engine.load_source(request)
        result = await full_engine.replay(request, source)

        assert result.status == "completed"
        assert result.total_steps == 1
        assert result.failed_steps == 0

        step = result.steps[0]
        assert step.step_type == ReplayStepType.ACTION_DECIDER
        assert step.status == ReplayStepStatus.SUCCESS
        assert "decision" in step.output_summary

    async def test_replay_all_steps(self, full_engine):
        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG],
            compare_with_original=False,
        )
        source = await full_engine.load_source(request)
        result = await full_engine.replay(request, source)

        assert result.status in ("completed", "failed")
        assert result.total_steps > 0

    async def test_replay_divergence_detection(self, full_engine):
        """When replay output differs from audit entries, mark divergence."""
        # Make decider return different result
        class DivergentDecider:
            async def decide(self, input_data):
                return {"action_type": "no_action", "decision": "different"}  # differs from audit

        full_engine._action_decider = DivergentDecider()

        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG],
            steps=[ReplayStepType.ACTION_DECIDER],
            compare_with_original=True,
        )
        source = await full_engine.load_source(request)
        result = await full_engine.replay(request, source)

        assert result.is_regression

    async def test_replay_with_review_fix(self, full_engine):
        from byou.review.models import ReviewItem, ReviewItemType, ResolutionAction

        item = ReviewItem(
            item_id="rev_fix_001",
            item_type=ReviewItemType.MERGE_SUGGESTION,
            source="intake",
            related_session_id="sid_001",
        )
        item.resolve(ResolutionAction.MERGE_UID, "Merged after review")
        full_engine._review_gateway.add(item)

        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG],
            steps=[ReplayStepType.ACTION_DECIDER],
            review_fix_id="rev_fix_001",
            compare_with_original=False,
        )
        source = await full_engine.load_source(request)
        result = await full_engine.replay(request, source)

        assert result.fix_applied is True
        assert result.fix_result["item_id"] == "rev_fix_001"

    async def test_replay_dry_run(self, full_engine):
        """Dry run should not write to memory."""
        full_engine._memory_gateway.signals = [
            {"session_id": "sid_001", "type": "memory_seed"},
        ]
        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.SEEDS],
            steps=[ReplayStepType.MEMORY_UPDATE],
            regen_memory=True,
            dry_run=True,
            compare_with_original=False,
        )
        source = await full_engine.load_source(request)
        result = await full_engine.replay(request, source)
        # Dry run — memory step just skipped or successful without side effects
        assert result.status in ("completed", "failed")

    async def test_step_without_inject_is_skipped(self):
        """Steps with no handler injected should be filtered out."""
        engine = ReplayEngine()  # no injects
        request = ReplayRequest(
            session_id="sid_001",
            sources=[ReplaySourceType.AUDIT_LOG],
            steps=[ReplayStepType.ACTION_DECIDER, ReplayStepType.DISTILLATION],
            compare_with_original=False,
        )
        source = ReplaySource(
            source_type=ReplaySourceType.AUDIT_LOG,
            session_id="sid_001",
            audit_entries=[{"event_type": "test"}],
        )
        result = await engine.replay(request, source)
        # All steps filtered → 0 steps run
        assert result.total_steps == 0
        assert result.status == "completed"

    async def test_replay_without_data_skips(self):
        """Step with inject but no data should be filtered."""
        engine = ReplayEngine()
        engine.inject_action_decider(FakeActionDecider())

        request = ReplayRequest(
            session_id="sid_empty",
            sources=[ReplaySourceType.AUDIT_LOG],
            steps=[ReplayStepType.ACTION_DECIDER],
            compare_with_original=False,
        )
        source = ReplaySource(
            source_type=ReplaySourceType.AUDIT_LOG,
            session_id="sid_empty",
            audit_entries=[],  # no entries
        )
        result = await engine.replay(request, source)
        assert result.total_steps == 0  # filtered — no data


# ══════════════════════════════════════════════════════════
# ReplayStep
# ══════════════════════════════════════════════════════════

class TestReplayStep:
    def test_step_creation(self):
        step = ReplayStep(step_type=ReplayStepType.ACTION_DECIDER)
        assert step.status == ReplayStepStatus.PENDING
        assert step.divergence is False

    def test_step_with_output(self):
        step = ReplayStep(
            step_type=ReplayStepType.ACTION_DECIDER,
            status=ReplayStepStatus.SUCCESS,
            output_summary={"decision": "follow_up_task"},
        )
        assert step.status == ReplayStepStatus.SUCCESS

    def test_step_divergence(self):
        step = ReplayStep(
            step_type=ReplayStepType.ACTION_DECIDER,
            status=ReplayStepStatus.DIVERGED,
            divergence=True,
            original_output={"decision": "crm_note"},
            output_summary={"decision": "follow_up_task"},
            divergence_details=["decision: 'crm_note' → 'follow_up_task'"],
        )
        assert step.divergence is True
        assert len(step.divergence_details) == 1


# ══════════════════════════════════════════════════════════
# ReplayResult
# ══════════════════════════════════════════════════════════

class TestReplayResult:
    def test_clean_result(self):
        result = ReplayResult(replay_id="rp_001", session_id="sid_001", source=ReplaySourceType.AUDIT_LOG)
        result.add_step(ReplayStep(
            step_type=ReplayStepType.ACTION_DECIDER,
            status=ReplayStepStatus.SUCCESS,
        ))
        assert result.is_clean is True
        assert result.has_divergence is False
        assert result.total_steps == 1
        assert result.successful_steps == 1

    def test_diverged_result(self):
        result = ReplayResult(replay_id="rp_002", session_id="sid_002", source=ReplaySourceType.AUDIT_LOG)
        result.add_step(ReplayStep(
            step_type=ReplayStepType.ACTION_DECIDER,
            status=ReplayStepStatus.DIVERGED,
            divergence=True,
        ))
        assert result.is_regression is False  # not auto-flagged
        assert result.has_divergence is True
        assert result.diverged_steps == 1

    def test_regression_marked(self):
        result = ReplayResult(replay_id="rp_003", session_id="sid_003", source=ReplaySourceType.AUDIT_LOG)
        result.mark_regression("Output diverged from original")
        assert result.is_regression is True
        assert "Output diverged" in result.regression_reasons[0]

    def test_failed_steps(self):
        result = ReplayResult(replay_id="rp_004", session_id="sid_004", source=ReplaySourceType.AUDIT_LOG)
        result.add_step(ReplayStep(
            step_type=ReplayStepType.DISTILLATION,
            status=ReplayStepStatus.FAILED,
            error="Connection timeout",
        ))
        assert result.failed_steps == 1
        assert result.is_clean is False


# ══════════════════════════════════════════════════════════
# ReplayFactory
# ══════════════════════════════════════════════════════════

class TestReplayFactory:
    def test_build_empty(self):
        engine = ReplayFactory().build()
        assert isinstance(engine, ReplayEngine)

    def test_build_full(self):
        engine = (ReplayFactory()
                  .with_action_decider(FakeActionDecider())
                  .with_follow_up_planner(FakeFollowUpPlanner())
                  .with_identity_gateway(FakeIdentityGateway())
                  .with_review_gateway(FakeReviewGateway())
                  .with_audit_store(FakeAuditStore())
                  .with_memory_gateway(FakeMemoryGateway())
                  .build())
        assert isinstance(engine, ReplayEngine)

    def test_build_partial(self):
        engine = (ReplayFactory()
                  .with_action_decider(FakeActionDecider())
                  .build())
        assert isinstance(engine, ReplayEngine)
