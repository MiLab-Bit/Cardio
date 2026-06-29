"""Byou L4 — Durable Execution Coordinator (统一门面)。

单例入口，管理所有 L4 子系统:
- Run/Stage 状态机
- Checkpoint 读写
- 失败恢复
- 回放 (Replay)
- 重跑 (Rerun)
- 幂等性
- 外部信号

用法:
    # 初始化 (在 Orchestrator 中)
    durable = DurableCoordinator(storage=SQLiteStorage())

    # 开始一个 run
    state = durable.start_run(run_id, trace_id)

    # 记录 stage 完成
    durable.record_stage_complete(run_id, "extraction", input_snap, output_snap)

    # 暂停等待审批
    durable.pause_for_approval(run_id, "strategy", approval_id)

    # 恢复
    durable.resume_run(run_id)

    # 失败恢复
    plan = durable.build_recovery_plan(run_id)
    result = await durable.execute_recovery(plan)

    # 回放
    result = await durable.replay(ReplayRequest(run_id=run_id))

    # 重跑
    result = await durable.rerun(RerunRequest(run_id=run_id, from_stage="research"))
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .checkpoints import CheckpointManager
from .idempotency import IdempotencyGuard
from .recovery import RecoveryCoordinator
from .replay import ReplayEngine
from .rerun import RerunEngine
from .reports import RecoveryReport, ReplayDiffReport, RerunReport, RunSummaryReport, build_run_summary
from .signals import SignalManager
from .state_machine import RunStateMachine, StageStateMachine
from .storage import BaseStorage, MemoryStorage, SQLiteStorage
from .types import (
    CheckpointRecord,
    IdempotencyKey,
    IdempotencyRecord,
    PipelineRunState,
    RecoveryAction,
    RecoveryDecision,
    RecoveryPlan,
    ReplayRequest,
    ReplayResult,
    RerunRequest,
    RerunResult,
    RunLifecycleEvent,
    RunStatus,
    SignalKind,
    StageExecStatus,
    StageExecutionState,
)

logger = logging.getLogger(__name__)


class DurableCoordinator:
    """L4 耐久执行统一门面"""

    def __init__(self, storage: BaseStorage | None = None):
        self._store = storage or MemoryStorage()
        self._checkpoints = CheckpointManager(self._store)
        self._signals = SignalManager()
        self._idempotency = IdempotencyGuard(self._store)
        self._recovery = RecoveryCoordinator(
            storage=self._store,
            signal_manager=self._signals,
            idempotency_guard=self._idempotency,
        )
        self._replay = ReplayEngine(self._store)
        self._rerun = RerunEngine(self._store)
        self._run_sm = RunStateMachine()
        self._stage_sm = StageStateMachine()

    # ── Run lifecycle ──────────────────────────────────────────

    def create_run(
        self,
        run_id: str,
        trace_id: str,
        card_image_path: str | None = None,
        audio_file_path: str | None = None,
        extra_context: dict[str, Any] | None = None,
        skip_stages: list[str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> PipelineRunState:
        """创建新的 run state"""
        state = PipelineRunState(
            run_id=run_id,
            trace_id=trace_id,
            status=RunStatus.PENDING,
            card_image_path=card_image_path,
            audio_file_path=audio_file_path,
            extra_context=extra_context or {},
            skip_stages=skip_stages or [],
            tags=tags or {},
        )
        self._store.save_run_state(state)
        evt = RunLifecycleEvent(
            run_id=run_id, event_type="created",
            to_status=RunStatus.PENDING,
        )
        self._store.save_event(evt)
        logger.info("Run created: %s", run_id)
        return state

    def start_run(self, run_id: str) -> PipelineRunState:
        """开始运行"""
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        state, evt = self._run_sm.start(state)
        self._store.save_run_state(state)
        self._store.save_event(evt)
        return state

    def complete_run(self, run_id: str) -> PipelineRunState:
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        state, evt = self._run_sm.complete(state)
        self._store.save_run_state(state)
        self._store.save_event(evt)
        return state

    def fail_run(self, run_id: str, error: str) -> PipelineRunState:
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        state, evt = self._run_sm.fail(state, error)
        self._store.save_run_state(state)
        self._store.save_event(evt)
        return state

    def cancel_run(self, run_id: str) -> PipelineRunState:
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        state, evt = self._run_sm.cancel(state)
        self._store.save_run_state(state)
        self._store.save_event(evt)
        return state

    # ── Stage lifecycle ───────────────────────────────────────

    def create_stage(self, run_id: str, stage_name: str, agent_name: str = "") -> StageExecutionState:
        s = StageExecutionState(run_id=run_id, stage_name=stage_name, agent_name=agent_name)
        self._store.save_stage_state(s)
        return s

    def start_stage(self, run_id: str, stage_name: str) -> StageExecutionState:
        s = self._store.load_stage_state(run_id, stage_name)
        if not s:
            s = self.create_stage(run_id, stage_name)
        s = self._stage_sm.start(s)
        self._store.save_stage_state(s)
        return s

    def complete_stage(
        self,
        run_id: str,
        stage_name: str,
        input_snapshot: dict[str, Any] | None = None,
        output_snapshot: dict[str, Any] | None = None,
    ) -> StageExecutionState:
        s = self._store.load_stage_state(run_id, stage_name)
        if not s:
            s = self.create_stage(run_id, stage_name)
        s = self._stage_sm.succeed(s)

        # 自动 checkpoint (如果是 checkpoint-需要的 stage)
        if self._checkpoints.stage_needs_checkpoint(stage_name):
            state = self._store.load_run_state(run_id)
            trace_id = state.trace_id if state else ""
            self._checkpoints.checkpoint_stage(
                run_id=run_id, trace_id=trace_id, stage_name=stage_name,
                stage_state=s, input_data=input_snapshot, output_data=output_snapshot,
                agent_name=s.agent_name,
            )

        self._store.save_stage_state(s)
        return s

    def fail_stage(self, run_id: str, stage_name: str, error: str) -> StageExecutionState:
        s = self._store.load_stage_state(run_id, stage_name)
        if not s:
            s = self.create_stage(run_id, stage_name)
        s = self._stage_sm.fail(s, error)
        self._store.save_stage_state(s)
        return s

    # ── Pause / Resume ─────────────────────────────────────────

    def pause_for_approval(
        self, run_id: str, stage_name: str, approval_request_id: str, reason: str = "",
    ) -> PipelineRunState:
        """暂停等待审批"""
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        state.current_stage = stage_name
        state, evt = self._run_sm.pause(state, reason, approval_request_id)
        self._store.save_run_state(state)
        self._store.save_event(evt)
        return state

    def resume_after_approval(self, run_id: str) -> PipelineRunState:
        """审批后恢复"""
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        state, evt = self._run_sm.resume(state)
        self._store.save_run_state(state)
        self._store.save_event(evt)
        return state

    # ── Recovery ───────────────────────────────────────────────

    def build_recovery_plan(self, run_id: str) -> RecoveryPlan:
        state = self._store.load_run_state(run_id)
        if not state:
            raise ValueError(f"Run {run_id} not found")
        return self._recovery.build_recovery_plan(state)

    async def execute_recovery(
        self, plan: RecoveryPlan, orchestrator=None, timeout_s: int = 3600,
    ) -> RecoveryDecision:
        return await self._recovery.execute_recovery(
            plan, orchestrator=orchestrator, timeout_s=timeout_s,
        )

    async def crash_recovery(self, run_id: str, orchestrator=None) -> RecoveryDecision:
        return await self._recovery.crash_recovery(run_id, orchestrator=orchestrator)

    # ── Replay ─────────────────────────────────────────────────

    async def replay(self, request: ReplayRequest) -> ReplayResult:
        return await self._replay.replay(request)

    def get_replay_summary(self, run_id: str) -> dict[str, Any]:
        return self._replay.get_replay_summary(run_id)

    # ── Rerun ──────────────────────────────────────────────────

    async def rerun(self, request: RerunRequest, orchestrator=None) -> RerunResult:
        return await self._rerun.rerun(request, orchestrator=orchestrator)

    # ── Checkpoint ─────────────────────────────────────────────

    def get_latest_checkpoint(self, run_id: str) -> CheckpointRecord | None:
        return self._checkpoints.get_latest_checkpoint(run_id)

    def list_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        return self._checkpoints.list_run_checkpoints(run_id)

    # ── Idempotency ────────────────────────────────────────────

    def check_idempotent(self, key: str) -> bool:
        return self._idempotency.is_duplicate(key)

    def record_idempotent(self, key: str, run_id: str, status: str = "completed") -> IdempotencyRecord:
        return self._idempotency.record(key=key, run_id=run_id, status=status)

    # ── Reports ────────────────────────────────────────────────

    def get_run_summary(self, run_id: str) -> RunSummaryReport:
        state = self._store.load_run_state(run_id)
        cps = self._checkpoints.list_run_checkpoints(run_id)
        events = self._store.list_events(run_id)
        return build_run_summary(state, len(cps), len(events))

    # ── Accessors ──────────────────────────────────────────────

    @property
    def store(self) -> BaseStorage:
        return self._store

    @property
    def signals(self) -> SignalManager:
        return self._signals

    @property
    def checkpoints(self) -> CheckpointManager:
        return self._checkpoints

    @property
    def idempotency(self) -> IdempotencyGuard:
        return self._idempotency
