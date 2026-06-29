"""L4 reliable execution 全覆盖测试."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from byou.production.execution import (
    BaseStorage,
    CheckpointManager,
    DurableCoordinator,
    IdempotencyGuard,
    MemoryStorage,
    ReplayEngine,
    RerunEngine,
    RunStateMachine,
    SignalManager,
    StageStateMachine,
    is_protected_action,
    wait_for_external_signal,
)
from byou.production.execution.types import (
    CheckpointRecord,
    IdempotencyKey,
    IdempotencyRecord,
    PipelineRunState,
    RecoveryAction,
    RecoveryPlan,
    ReplayRequest,
    RerunRequest,
    RunLifecycleEvent,
    RunStatus,
    SignalKind,
    StageExecStatus,
    StageExecutionState,
)


# ═══════════════════════════════════════════════════════════════
# 1. Types — 模型验证
# ═══════════════════════════════════════════════════════════════

class TestTypes:
    def test_run_status_enum(self):
        assert RunStatus.PENDING.value == "pending"
        assert RunStatus.COMPLETED.terminal is True
        assert RunStatus.FAILED.terminal is True
        assert RunStatus.RUNNING.terminal is False
        assert RunStatus.PAUSED.resumable is True
        assert RunStatus.WAITING_SIGNAL.resumable is True

    def test_pipeline_run_state_defaults(self):
        state = PipelineRunState(run_id="r1", trace_id="t1")
        assert state.status == RunStatus.PENDING
        assert state.retry_count == 0
        assert state.max_retries == 3
        assert state.created_at is not None

    def test_stage_execution_state(self):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        assert s.status == StageExecStatus.PENDING
        assert s.retry_count == 0

    def test_checkpoint_record(self):
        cp = CheckpointRecord(
            run_id="r1", trace_id="t1", stage="extraction",
            input_snapshot={"card": "data"}, output_snapshot={"name": "张三"},
        )
        assert len(cp.checkpoint_id) > 0
        assert cp.resumable is True
        assert cp.status == StageExecStatus.SUCCESS

    def test_recovery_plan(self):
        plan = RecoveryPlan(
            run_id="r1", current_status=RunStatus.FAILED,
            failed_stage="research",
            suggested_action=RecoveryAction.RETRY_STAGE,
        )
        assert plan.run_id == "r1"
        assert plan.suggested_action == RecoveryAction.RETRY_STAGE

    def test_replay_request(self):
        req = ReplayRequest(run_id="r1", dry_run=True, max_retries=3)
        assert req.dry_run is True
        assert req.from_stage is None

    def test_rerun_request(self):
        req = RerunRequest(run_id="r1", from_stage="research", reuse_checkpoints=True)
        assert req.from_stage == "research"
        assert req.reuse_checkpoints is True

    def test_idempotency_key(self):
        ik = IdempotencyKey(key="crm:abc", run_id="r1", stage="synthesis", action="crm_write", resource="company_123")
        assert ik.key == "crm:abc"
        assert ik.action == "crm_write"

    def test_external_signal(self):
        from byou.production.execution.types import ExternalSignal
        sig = ExternalSignal(run_id="r1", kind=SignalKind.APPROVAL_DECISION)
        assert len(sig.signal_id) > 0
        assert sig.processed is False

    def test_lifecycle_event(self):
        evt = RunLifecycleEvent(
            run_id="r1", event_type="started",
            from_status=RunStatus.PENDING, to_status=RunStatus.RUNNING,
        )
        assert evt.event_id
        assert evt.event_type == "started"


# ═══════════════════════════════════════════════════════════════
# 2. Storage — 多后端
# ═══════════════════════════════════════════════════════════════

class TestMemoryStorage:
    @pytest.fixture
    def store(self):
        return MemoryStorage()

    def test_save_and_load_run(self, store):
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.RUNNING)
        store.save_run_state(state)
        loaded = store.load_run_state("r1")
        assert loaded is not None
        assert loaded.run_id == "r1"
        assert loaded.status == RunStatus.RUNNING

    def test_load_nonexistent(self, store):
        assert store.load_run_state("nonexistent") is None

    def test_stage_state(self, store):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        store.save_stage_state(s)
        loaded = store.load_stage_state("r1", "extraction")
        assert loaded is not None
        assert loaded.stage_name == "extraction"

    def test_checkpoint_crud(self, store):
        cp = CheckpointRecord(run_id="r1", trace_id="t1", stage="extraction")
        store.save_checkpoint(cp)
        loaded = store.load_checkpoint(cp.checkpoint_id)
        assert loaded is not None
        assert loaded.stage == "extraction"

    def test_list_checkpoints_by_run(self, store):
        cp1 = CheckpointRecord(run_id="r1", trace_id="t1", stage="extraction")
        cp2 = CheckpointRecord(run_id="r1", trace_id="t1", stage="research")
        cp3 = CheckpointRecord(run_id="r2", trace_id="t2", stage="extraction")
        for cp in [cp1, cp2, cp3]:
            store.save_checkpoint(cp)
        assert len(store.list_checkpoints("r1")) == 2
        assert len(store.list_checkpoints("r2")) == 1

    def test_events(self, store):
        evt = RunLifecycleEvent(run_id="r1", event_type="started")
        store.save_event(evt)
        events = store.list_events("r1")
        assert len(events) == 1
        assert events[0].event_type == "started"

    def test_idempotency(self, store):
        rec = IdempotencyRecord(key="crm:abc", status="completed", run_id="r1")
        store.save_idempotency(rec)
        loaded = store.get_idempotency("crm:abc")
        assert loaded is not None
        assert loaded.status == "completed"

    def test_idempotency_not_found(self, store):
        assert store.get_idempotency("nonexistent") is None


# ═══════════════════════════════════════════════════════════════
# 3. StateMachine — 状态转换
# ═══════════════════════════════════════════════════════════════

class TestRunStateMachine:
    @pytest.fixture
    def sm(self):
        return RunStateMachine()

    @pytest.fixture
    def state(self):
        return PipelineRunState(run_id="r1", trace_id="t1")

    def test_valid_transitions(self, sm, state):
        state.status = RunStatus.RUNNING
        ok, _ = sm.transition(state, RunStatus.PAUSED)
        assert ok is True

    def test_invalid_transition(self, sm, state):
        # completed → running is invalid
        state.status = RunStatus.COMPLETED
        ok, msg = sm.transition(state, RunStatus.RUNNING)
        assert ok is False

    def test_start(self, sm, state):
        state, evt = sm.start(state)
        assert state.status == RunStatus.RUNNING
        assert state.started_at is not None

    def test_pause(self, sm, state):
        state.status = RunStatus.RUNNING
        state, evt = sm.pause(state, "awaiting approval")
        assert state.status == RunStatus.PAUSED
        assert state.pause_reason == "awaiting approval"

    def test_resume(self, sm, state):
        state.status = RunStatus.PAUSED
        state, evt = sm.resume(state)
        assert state.status == RunStatus.RUNNING
        assert state.pause_reason is None

    def test_complete(self, sm, state):
        state.status = RunStatus.RUNNING
        state, evt = sm.complete(state)
        assert state.status == RunStatus.COMPLETED

    def test_fail(self, sm, state):
        state.status = RunStatus.RUNNING
        state, evt = sm.fail(state, "connection error")
        assert state.status == RunStatus.FAILED
        assert state.error_message == "connection error"

    def test_retry_success(self, sm, state):
        state.status = RunStatus.FAILED
        new_state, evt, err = sm.retry(state)
        assert new_state is not None
        assert new_state.status == RunStatus.RETRYING
        assert new_state.retry_count == 1
        assert err == ""

    def test_retry_max_exceeded(self, sm, state):
        state.status = RunStatus.FAILED
        state.retry_count = 3
        state.max_retries = 3
        new_state, evt, err = sm.retry(state)
        assert new_state is None
        assert "exceeded" in err.lower()

    def test_cancel(self, sm, state):
        state.status = RunStatus.RUNNING
        state, evt = sm.cancel(state)
        assert state.status == RunStatus.CANCELLED


class TestStageStateMachine:
    @pytest.fixture
    def sm(self):
        return StageStateMachine()

    def test_start(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s = sm.start(s)
        assert s.status == StageExecStatus.RUNNING

    def test_succeed(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s = sm.start(s)
        s = sm.succeed(s)
        assert s.status == StageExecStatus.SUCCESS
        assert s.duration_ms >= 0

    def test_fail(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s = sm.start(s)
        s = sm.fail(s, "timeout")
        assert s.status == StageExecStatus.FAILED
        assert s.error == "timeout"

    def test_retry(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s.status = StageExecStatus.FAILED
        result = sm.retry(s)
        assert result is not None
        assert result.status == StageExecStatus.RETRYING

    def test_retry_max(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s.status = StageExecStatus.FAILED
        s.retry_count = 3
        result = sm.retry(s)
        assert result is None

    def test_skip(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s = sm.skip(s)
        assert s.status == StageExecStatus.SKIPPED

    def test_valid_transition(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        ok, _ = sm.transition(s, StageExecStatus.RUNNING)
        assert ok is True

    def test_invalid_transition(self, sm):
        s = StageExecutionState(run_id="r1", stage_name="extraction")
        s.status = StageExecStatus.SUCCESS
        ok, msg = sm.transition(s, StageExecStatus.RUNNING)
        assert ok is False


# ═══════════════════════════════════════════════════════════════
# 4. Checkpoints
# ═══════════════════════════════════════════════════════════════

class TestCheckpointManager:
    @pytest.fixture
    def store(self):
        return MemoryStorage()

    @pytest.fixture
    def cp_mgr(self, store):
        return CheckpointManager(store)

    def test_stage_checkpoint(self, cp_mgr):
        s = StageExecutionState(run_id="r1", stage_name="extraction", status=StageExecStatus.SUCCESS)
        cp = cp_mgr.checkpoint_stage("r1", "t1", "extraction", s, {"card": "data"}, {"name": "张三"})
        assert cp.stage == "extraction"
        assert cp.resumable is True
        assert cp.checkpoint_id in s.checkpoint_ids

    def test_substep_checkpoint(self, cp_mgr):
        cp = cp_mgr.checkpoint_substep("r1", "t1", "research", "enrichment", StageExecStatus.SUCCESS)
        assert cp.step == "enrichment"

    def test_pause_checkpoint(self, cp_mgr):
        cp = cp_mgr.checkpoint_pause("r1", "t1", "strategy", "approval pending")
        assert cp.stage == "strategy"
        assert cp.step == "pause"
        assert cp.extra.get("pause_reason") == "approval pending"

    def test_get_latest_checkpoint(self, cp_mgr):
        cp_mgr.checkpoint_stage("r1", "t1", "extraction", StageExecutionState(run_id="r1", stage_name="extraction"))
        cp_mgr.checkpoint_stage("r1", "t1", "research", StageExecutionState(run_id="r1", stage_name="research"))
        latest = cp_mgr.get_latest_checkpoint("r1")
        assert latest is not None
        assert latest.stage == "research"

    def test_get_latest_resumable(self, cp_mgr):
        s_ext = StageExecutionState(run_id="r1", stage_name="extraction", status=StageExecStatus.SUCCESS)
        cp_mgr.checkpoint_stage("r1", "t1", "extraction", s_ext)
        # non-resumable checkpoint
        cp = CheckpointRecord(run_id="r1", trace_id="t1", stage="research", status=StageExecStatus.FAILED, resumable=False)
        cp_mgr._store.save_checkpoint(cp)
        latest = cp_mgr.get_latest_resumable("r1")
        assert latest is not None
        assert latest.stage == "extraction"  # research is not resumable

    def test_get_stage_checkpoint(self, cp_mgr):
        cp_mgr.checkpoint_stage("r1", "t1", "extraction", StageExecutionState(run_id="r1", stage_name="extraction"))
        cp = cp_mgr.get_stage_checkpoint("r1", "extraction")
        assert cp is not None
        assert cp.stage == "extraction"

    def test_stage_needs_checkpoint(self):
        assert CheckpointManager.stage_needs_checkpoint("extraction") is True
        assert CheckpointManager.stage_needs_checkpoint("research") is True
        assert CheckpointManager.stage_needs_checkpoint("unknown") is False

    def test_substep_needs_checkpoint(self):
        assert CheckpointManager.substep_needs_checkpoint("enrichment") is True
        assert CheckpointManager.substep_needs_checkpoint("browser") is True
        assert CheckpointManager.substep_needs_checkpoint("unknown") is False


# ═══════════════════════════════════════════════════════════════
# 5. Idempotency
# ═══════════════════════════════════════════════════════════════

class TestIdempotencyGuard:
    @pytest.fixture
    def store(self):
        return MemoryStorage()

    @pytest.fixture
    def guard(self, store):
        return IdempotencyGuard(store)

    def test_make_key(self):
        key = IdempotencyGuard.make_key("run_1234567890", "crm_write", "company:张三")
        assert "crm_write" in key
        assert "7890" in key  # run suffix

    def test_not_duplicate(self, guard):
        assert guard.is_duplicate("crm:test") is False

    def test_is_duplicate_after_record(self, guard):
        guard.record("crm:test", "r1", status="completed")
        assert guard.is_duplicate("crm:test") is True

    def test_in_progress_not_duplicate(self, guard):
        guard.record("crm:test", "r1", status="in_progress")
        assert guard.is_duplicate("crm:test") is False

    def test_wrap_should_execute(self, guard):
        should_execute, ik = guard.wrap("crm:new", "r1", "crm_write", "company_001")
        assert should_execute is True

    def test_wrap_skip_duplicate(self, guard):
        guard.record("crm:dup", "r1", status="completed")
        should_execute, ik = guard.wrap("crm:dup", "r1", "crm_write", "company_001")
        assert should_execute is False

    def test_is_protected_action(self):
        assert is_protected_action("crm_write") is True
        assert is_protected_action("memory_insert") is True
        assert is_protected_action("browser_form_submit") is True
        assert is_protected_action("enrichment_api_call") is True
        assert is_protected_action("email_send") is True
        assert is_protected_action("read_contact") is False
        assert is_protected_action("unknown_action") is False


# ═══════════════════════════════════════════════════════════════
# 6. Signals
# ═══════════════════════════════════════════════════════════════

class TestSignalManager:
    @pytest.fixture
    def sm(self):
        return SignalManager()

    def test_register_signal(self, sm):
        sig = sm.register_signal("r1", SignalKind.APPROVAL_DECISION)
        assert len(sm) == 1
        pending = sm.get_pending_for_run("r1")
        assert len(pending) == 1

    def test_resolve_signal(self, sm):
        sig = sm.register_signal("r1", SignalKind.APPROVAL_DECISION)
        resolved = sm.resolve_signal(sig.signal_id)
        assert resolved is not None
        assert resolved.processed is True
        assert len(sm) == 0

    def test_resolve_by_run(self, sm):
        sm.register_signal("r1", SignalKind.APPROVAL_DECISION)
        sm.register_signal("r1", SignalKind.WEBHOOK_CALLBACK)
        resolved = sm.resolve_for_run("r1")
        assert len(resolved) == 2
        assert len(sm) == 0

    def test_clear_run(self, sm):
        sm.register_signal("r1", SignalKind.APPROVAL_DECISION)
        count = sm.clear_run("r1")
        assert count == 1
        assert len(sm) == 0

    def test_get_expired(self, sm):
        # 手动回溯 received_at 使其过期
        sig = sm.register_signal("r1", SignalKind.APPROVAL_DECISION, timeout_s=1)
        from datetime import datetime, timezone, timedelta
        sig.received_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        expired = sm.get_expired()
        assert len(expired) >= 1

    def test_no_timeout_signal_not_expired(self, sm):
        sig = sm.register_signal("r1", SignalKind.APPROVAL_DECISION, timeout_s=99999)
        expired = sm.get_expired()
        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_wait_for_signal_success(self, sm):
        async def resolve_after_delay():
            await asyncio.sleep(0.2)
            sm.resolve_for_run("r1")

        sm.register_signal("r1", SignalKind.APPROVAL_DECISION)
        task = asyncio.create_task(resolve_after_delay())
        result = await wait_for_external_signal("r1", sm, timeout_s=5, poll_interval_s=0.1)
        await task
        assert result is not None
        assert result.processed is True

    @pytest.mark.asyncio
    async def test_wait_for_signal_timeout(self, sm):
        # 不注册任何信号, 等待超时
        result = await wait_for_external_signal("r1", sm, timeout_s=0.3, poll_interval_s=0.1)
        assert result is None


# ═══════════════════════════════════════════════════════════════
# 7. Recovery
# ═══════════════════════════════════════════════════════════════

class TestRecovery:
    @pytest.fixture
    def store(self):
        return MemoryStorage()

    def test_analyse_found(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1")
        store.save_run_state(state)
        result = rc.analyse("r1")
        assert result is not None
        assert result.run_id == "r1"

    def test_analyse_not_found(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        assert rc.analyse("nonexistent") is None

    def test_build_recovery_plan_failed(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.FAILED)
        store.save_run_state(state)
        plan = rc.build_recovery_plan(state)
        assert plan.suggested_action == RecoveryAction.RERUN_FROM_STAGE

    def test_build_recovery_plan_paused(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.PAUSED)
        store.save_run_state(state)
        plan = rc.build_recovery_plan(state)
        assert plan.suggested_action == RecoveryAction.RESUME_RUN

    def test_build_recovery_plan_running(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.RUNNING)
        store.save_run_state(state)
        plan = rc.build_recovery_plan(state)
        assert plan.suggested_action == RecoveryAction.RETRY_STAGE

    def test_build_recovery_plan_completed(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.COMPLETED)
        store.save_run_state(state)
        plan = rc.build_recovery_plan(state)
        assert plan.suggested_action == RecoveryAction.REPLAY_RUN

    @pytest.mark.asyncio
    async def test_handle_retry_stage(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.FAILED)
        store.save_run_state(state)
        decision = await rc._handle_retry_stage(state, RecoveryPlan(
            run_id="r1", current_status=RunStatus.FAILED, suggested_action=RecoveryAction.RETRY_STAGE,
        ), None, None, None, 300)
        assert decision.success is True
        assert decision.new_status == RunStatus.RETRYING

    @pytest.mark.asyncio
    async def test_handle_resume_from_paused(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.PAUSED)
        store.save_run_state(state)
        decision = await rc._handle_resume(state, RecoveryPlan(
            run_id="r1", current_status=RunStatus.PAUSED, suggested_action=RecoveryAction.RESUME_RUN,
        ), None, None, None, 300)
        assert decision.success is True
        assert decision.new_status == RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_handle_cancel(self, store):
        from byou.production.execution.recovery import RecoveryCoordinator
        rc = RecoveryCoordinator(store)
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.RUNNING)
        store.save_run_state(state)
        decision = await rc._handle_cancel(state, RecoveryPlan(
            run_id="r1", current_status=RunStatus.RUNNING, suggested_action=RecoveryAction.CANCEL_RUN,
        ), None, None, None, 300)
        assert decision.success is True
        assert decision.new_status == RunStatus.CANCELLED


# ═══════════════════════════════════════════════════════════════
# 8. Replay
# ═══════════════════════════════════════════════════════════════

class TestReplay:
    @pytest.fixture
    def store(self):
        s = MemoryStorage()
        state = PipelineRunState(run_id="r1", trace_id="t1", status=RunStatus.COMPLETED)
        s.save_run_state(state)
        return s

    @pytest.mark.asyncio
    async def test_replay_with_checkpoints(self, store):
        engine = ReplayEngine(store)
        cp_mgr = CheckpointManager(store)
        cp_mgr.checkpoint_stage("r1", "t1", "extraction",
            StageExecutionState(run_id="r1", stage_name="extraction"),
            output_data={"name": "张三"})
        cp_mgr.checkpoint_stage("r1", "t1", "research",
            StageExecutionState(run_id="r1", stage_name="research"),
            output_data={"company": "Tech Co."})

        result = await engine.replay(ReplayRequest(run_id="r1"))
        assert result.success is True
        assert result.original_run_id == "r1"
        assert result.stages_replayed >= 2

    @pytest.mark.asyncio
    async def test_replay_no_checkpoints(self, store):
        engine = ReplayEngine(store)
        result = await engine.replay(ReplayRequest(run_id="r1"))
        assert result.success is False
        assert "No checkpoints" in result.errors[0]

    @pytest.mark.asyncio
    async def test_replay_not_found(self, store):
        engine = ReplayEngine(store)
        result = await engine.replay(ReplayRequest(run_id="nonexistent"))
        assert result.success is False

    def test_replay_summary(self, store):
        engine = ReplayEngine(store)
        cp_mgr = CheckpointManager(store)
        cp_mgr.checkpoint_stage("r1", "t1", "extraction",
            StageExecutionState(run_id="r1", stage_name="extraction"))
        summary = engine.get_replay_summary("r1")
        assert summary["run_id"] == "r1"
        assert summary["checkpoint_count"] >= 1


# ═══════════════════════════════════════════════════════════════
# 9. Rerun
# ═══════════════════════════════════════════════════════════════

class TestRerun:
    @pytest.fixture
    def store(self):
        s = MemoryStorage()
        state = PipelineRunState(
            run_id="r1", trace_id="t1", status=RunStatus.FAILED,
            card_image_path="/tmp/card.png",
        )
        s.save_run_state(state)
        return s

    @pytest.mark.asyncio
    async def test_rerun_from_research(self, store):
        engine = RerunEngine(store)
        cp_mgr = CheckpointManager(store)
        s = StageExecutionState(run_id="r1", stage_name="extraction", status=StageExecStatus.SUCCESS)
        cp_mgr.checkpoint_stage("r1", "t1", "extraction", s,
            output_data={"name": "张三"})

        result = await engine.rerun(RerunRequest(run_id="r1", from_stage="research"))
        assert result.success is True
        assert len(result.new_run_id) > 0
        assert "extraction" in result.reused_stages
        assert "research" in result.reran_stages

    @pytest.mark.asyncio
    async def test_rerun_from_first_stage(self, store):
        engine = RerunEngine(store)
        result = await engine.rerun(RerunRequest(run_id="r1", from_stage="extraction", reuse_checkpoints=False))
        assert result.success is True
        assert len(result.reused_stages) == 0
        assert "extraction" in result.reran_stages

    @pytest.mark.asyncio
    async def test_rerun_unknown_run(self, store):
        engine = RerunEngine(store)
        result = await engine.rerun(RerunRequest(run_id="nonexistent", from_stage="research"))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_rerun_invalid_stage(self, store):
        engine = RerunEngine(store)
        result = await engine.rerun(RerunRequest(run_id="r1", from_stage="invalid_stage"))
        assert result.success is False

    def test_get_stage_order(self, store):
        engine = RerunEngine(store)
        assert engine.get_stage_order("extraction") == 0
        assert engine.get_stage_order("critique") == 4
        assert engine.get_stage_order("unknown") == -1

    def test_get_remaining_stages(self, store):
        engine = RerunEngine(store)
        remaining = engine.get_remaining_stages("research")
        assert remaining == ["research", "synthesis", "strategy", "critique"]


# ═══════════════════════════════════════════════════════════════
# 10. Coordinator — 统一门面
# ═══════════════════════════════════════════════════════════════

class TestDurableCoordinator:
    @pytest.fixture
    def coord(self):
        return DurableCoordinator(storage=MemoryStorage())

    def test_create_and_start_run(self, coord):
        coord.create_run("r1", "t1")
        state = coord.start_run("r1")
        assert state.status == RunStatus.RUNNING

    def test_complete_run(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        state = coord.complete_run("r1")
        assert state.status == RunStatus.COMPLETED

    def test_fail_run(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        state = coord.fail_run("r1", "connection error")
        assert state.status == RunStatus.FAILED

    def test_full_stage_lifecycle(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        s = coord.start_stage("r1", "extraction")
        assert s.status == StageExecStatus.RUNNING
        s = coord.complete_stage("r1", "extraction", {"card": "data"}, {"name": "张三"})
        assert s.status == StageExecStatus.SUCCESS
        # Checkpoint auto-created
        assert len(s.checkpoint_ids) >= 1

    def test_pause_for_approval(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        state = coord.pause_for_approval("r1", "strategy", "appr_001")
        assert state.status == RunStatus.PAUSED
        assert state.approval_request_id == "appr_001"

    def test_resume_after_approval(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        coord.pause_for_approval("r1", "strategy", "appr_001")
        state = coord.resume_after_approval("r1")
        assert state.status == RunStatus.RUNNING
        assert state.approval_request_id is None

    def test_idempotency_flow(self, coord):
        # 第一次 — 未完成
        assert coord.check_idempotent("crm:test") is False
        # 记录完成
        coord.record_idempotent("crm:test", "r1")
        # 第二次 — 已完成
        assert coord.check_idempotent("crm:test") is True

    def test_run_summary(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        coord.start_stage("r1", "extraction")
        coord.complete_stage("r1", "extraction")
        coord.complete_run("r1")
        summary = coord.get_run_summary("r1")
        assert summary.run_id == "r1"
        assert summary.status == "completed"
        assert summary.total_checkpoints >= 1

    def test_recovery_plan_builder(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        coord.fail_run("r1", "test error")
        plan = coord.build_recovery_plan("r1")
        assert plan.suggested_action == RecoveryAction.RERUN_FROM_STAGE

    @pytest.mark.asyncio
    async def test_crash_recovery(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        coord.complete_run("r1")
        decision = await coord.crash_recovery("r1")
        assert decision.success is True

    @pytest.mark.asyncio
    async def test_replay_flow(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        coord.start_stage("r1", "extraction")
        coord.complete_stage("r1", "extraction", output_snapshot={"name": "张三"})
        coord.complete_run("r1")
        result = await coord.replay(ReplayRequest(run_id="r1"))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_rerun_flow(self, coord):
        coord.create_run("r1", "t1")
        coord.start_run("r1")
        coord.start_stage("r1", "extraction")
        coord.complete_stage("r1", "extraction", output_snapshot={"name": "张三"})
        coord.fail_run("r1", "research error")
        result = await coord.rerun(RerunRequest(run_id="r1", from_stage="research"))
        assert result.success is True
        assert "extraction" in result.reused_stages
        assert len(result.new_run_id) > 0


# ═══════════════════════════════════════════════════════════════
# 11. Fixtures — 测试数据
# ═══════════════════════════════════════════════════════════════

class TestFixtures:
    def test_sample_runs_loaded(self):
        fixture_path = Path(__file__).parent.parent.parent.parent / "byou" / "production" / "durable" / "fixtures" / "sample_runs.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                data = json.load(f)
            assert "run_001" in data
            assert data["run_001"]["status"] == "completed"

    def test_recovery_cases_loaded(self):
        fixture_path = Path(__file__).parent.parent.parent.parent / "byou" / "production" / "durable" / "fixtures" / "recovery_cases.json"
        if fixture_path.exists():
            with open(fixture_path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) >= 5
            cases = {c["case"] for c in data}
            assert "crash_during_extraction" in cases
            assert "paused_approval" in cases
            assert "max_retries_exceeded" in cases
