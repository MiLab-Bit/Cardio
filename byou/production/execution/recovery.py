"""Byou L4 — 失败恢复决策与执行。

主入口: RecoveryCoordinator — 分析 run 状态 → 决定恢复方案 → 执行恢复。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .checkpoints import CheckpointManager, build_recovery_payload
from .idempotency import IdempotencyGuard
from .signals import SignalManager, wait_for_external_signal
from .state_machine import RECOVERY_ACTION_MAP, RunStateMachine
from .storage import BaseStorage
from .types import (
    CheckpointRecord,
    PipelineRunState,
    RecoveryAction,
    RecoveryDecision,
    RecoveryPlan,
    RunLifecycleEvent,
    RunStatus,
    SignalKind,
    StageExecStatus,
    StageExecutionState,
)

logger = logging.getLogger(__name__)


class RecoveryCoordinator:
    """统一恢复入口 — 分析 + 决策 + 执行"""

    def __init__(
        self,
        storage: BaseStorage,
        signal_manager: SignalManager | None = None,
        idempotency_guard: IdempotencyGuard | None = None,
    ):
        self._store = storage
        self._checkpoints = CheckpointManager(storage)
        self._signals = signal_manager or SignalManager()
        self._idempotency = idempotency_guard or IdempotencyGuard(storage)
        self._state_machine = RunStateMachine()

    # ── Phase 1: Analyse ───────────────────────────────────────

    def analyse(self, run_id: str) -> PipelineRunState | None:
        """加载 run 状态，返回 None 说明没有历史记录"""
        return self._store.load_run_state(run_id)

    def build_recovery_plan(self, run_state: PipelineRunState) -> RecoveryPlan:
        """基于 run 状态构建恢复计划"""
        action = RECOVERY_ACTION_MAP.get(run_state.status, RecoveryAction.RESTART_RUN)

        # 获取可用 checkpoints
        cps = self._checkpoints.list_run_checkpoints(run_state.run_id)
        available_ids = [c.checkpoint_id for c in cps if c.resumable]

        # 选择恢复起点
        resume_from = None
        latest = self._checkpoints.get_latest_resumable(run_state.run_id)
        if latest:
            resume_from = latest.checkpoint_id

        reason = self._build_reason(run_state, action, latest)

        return RecoveryPlan(
            run_id=run_state.run_id,
            current_status=run_state.status,
            failed_stage=run_state.current_stage,
            suggested_action=action,
            available_checkpoints=available_ids,
            resume_from_checkpoint=resume_from,
            reason=reason,
        )

    def _build_reason(
        self, state: PipelineRunState, action: RecoveryAction, checkpoint: CheckpointRecord | None,
    ) -> str:
        """生成恢复原因说明"""
        if action == RecoveryAction.RESUME_RUN:
            return f"Resuming from {state.status.value}; reason={state.pause_reason or 'unknown'}"
        if action == RecoveryAction.RETRY_STAGE:
            stage = state.current_stage or "unknown"
            return f"Retrying stage '{stage}' after crash/error"
        if action == RecoveryAction.RERUN_FROM_STAGE:
            ckpt = checkpoint.stage if checkpoint else "extraction"
            return f"Rerun from stage '{ckpt}' after failure"
        if action == RecoveryAction.RESTART_RUN:
            return "Full restart — no recoverable state"
        if action == RecoveryAction.REPLAY_RUN:
            return "Replaying completed run for analysis"
        return f"Recovery action: {action.value}"

    # ── Phase 2: Execute ───────────────────────────────────────

    async def execute_recovery(
        self,
        plan: RecoveryPlan,
        *,
        orchestrator=None,           # Orchestrator 实例
        on_decision: Any = None,     # 外部审批决策
        run_fn=None,                  # 用户提供的执行函数
        timeout_s: int = 3600,
    ) -> RecoveryDecision:
        """执行恢复计划"""
        started_at = datetime.now(timezone.utc)
        run_state = self._store.load_run_state(plan.run_id)
        if not run_state:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message=f"Run {plan.run_id} not found",
            )

        action_handlers = {
            RecoveryAction.RETRY_STAGE: self._handle_retry_stage,
            RecoveryAction.RESUME_RUN: self._handle_resume,
            RecoveryAction.RERUN_FROM_STAGE: self._handle_rerun,
            RecoveryAction.RESTART_RUN: self._handle_restart,
            RecoveryAction.REPLAY_RUN: self._handle_replay,
            RecoveryAction.CANCEL_RUN: self._handle_cancel,
            RecoveryAction.ESCALATE: self._handle_escalate,
        }

        handler = action_handlers.get(plan.suggested_action)
        if handler is None:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message=f"Unknown action: {plan.suggested_action}",
            )

        result = await handler(run_state, plan, orchestrator, on_decision, run_fn, timeout_s)

        duration = (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
        result.duration_ms = duration
        return result

    # ── Handlers ───────────────────────────────────────────────

    async def _handle_retry_stage(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        """重试当前失败的 stage"""
        if state.retry_count >= state.max_retries:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message=f"Max retries ({state.max_retries}) exceeded",
            )

        new_state, evt, err_msg = self._state_machine.retry(state)
        if new_state is None:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message=err_msg or "Retry rejected by state machine",
            )

        self._store.save_run_state(new_state)
        if evt:
            self._store.save_event(evt)

        return RecoveryDecision(
            run_id=plan.run_id, action=plan.suggested_action, success=True,
            resumed_at=datetime.now(timezone.utc),
            new_status=RunStatus.RETRYING,
            message=f"Stage retry approved (attempt {new_state.retry_count}/{new_state.max_retries})",
        )

    async def _handle_resume(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        """从暂停/等待信号恢复"""
        if state.status not in (RunStatus.PAUSED, RunStatus.WAITING_SIGNAL):
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message=f"Cannot resume from {state.status.value}",
            )

        if state.status == RunStatus.WAITING_SIGNAL:
            signal = await wait_for_external_signal(
                plan.run_id, self._signals,
                timeout_s=min(state.approval_request_id and 600 or 300, timeout_s),
            )
            if not signal:
                new_state, evt = self._state_machine.fail(state, "Signal timeout")
                self._store.save_run_state(new_state)
                self._store.save_event(evt)
                return RecoveryDecision(
                    run_id=plan.run_id, action=plan.suggested_action, success=False,
                    message="Signal timeout — run marked as failed",
                )

        new_state, evt = self._state_machine.resume(state)
        self._store.save_run_state(new_state)
        self._store.save_event(evt)

        return RecoveryDecision(
            run_id=plan.run_id, action=plan.suggested_action, success=True,
            resumed_at=new_state.resumed_at,
            new_status=RunStatus.RUNNING,
            message=f"Run resumed from {state.status.value}",
        )

    async def _handle_rerun(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        """从指定 stage 重跑"""
        resume_from_checkpoint = plan.resume_from_checkpoint
        if not resume_from_checkpoint:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message="No resumable checkpoint available for rerun",
            )

        cp = self._checkpoints._store.load_checkpoint(resume_from_checkpoint)
        if not cp:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message=f"Checkpoint {resume_from_checkpoint} not found",
            )

        state.status = RunStatus.RUNNING
        state.current_stage = cp.stage
        state.error_message = None
        self._store.save_run_state(state)

        evt = RunLifecycleEvent(
            run_id=plan.run_id, event_type="rerun_started",
            from_status=RunStatus.FAILED, to_status=RunStatus.RUNNING,
            stage=cp.stage, details={"from_checkpoint": cp.checkpoint_id},
        )
        self._store.save_event(evt)

        return RecoveryDecision(
            run_id=plan.run_id, action=plan.suggested_action, success=True,
            resumed_at=datetime.now(timezone.utc),
            new_status=RunStatus.RUNNING,
            message=f"Rerun from stage '{cp.stage}' (checkpoint={cp.checkpoint_id})",
        )

    async def _handle_restart(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        """从头重启"""
        new_run_id = uuid4().hex[:12]

        new_state = PipelineRunState(
            run_id=new_run_id,
            trace_id=uuid4().hex[:16],
            status=RunStatus.PENDING,
            card_image_path=state.card_image_path,
            audio_file_path=state.audio_file_path,
            extra_context=state.extra_context,
            tags={**state.tags, "restarted_from": state.run_id},
        )
        self._store.save_run_state(new_state)

        evt = RunLifecycleEvent(
            run_id=new_run_id, event_type="restarted",
            from_status=None, to_status=RunStatus.PENDING,
            details={"original_run_id": state.run_id},
        )
        self._store.save_event(evt)

        return RecoveryDecision(
            run_id=new_run_id, action=plan.suggested_action, success=True,
            resumed_at=datetime.now(timezone.utc),
            new_status=RunStatus.PENDING,
            message=f"Restarted as new run {new_run_id} (from {state.run_id})",
        )

    async def _handle_replay(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        """重放运行 (分析模式)"""
        allowed, err = self._state_machine.transition(state, RunStatus.REPLAYING)
        if not allowed:
            return RecoveryDecision(
                run_id=plan.run_id, action=plan.suggested_action, success=False,
                message="Cannot transition to REPLAYING",
            )
        state.status = RunStatus.REPLAYING
        self._store.save_run_state(state)

        replay_evt = RunLifecycleEvent(
            run_id=plan.run_id, event_type="replay_started",
            from_status=RunStatus.COMPLETED, to_status=RunStatus.REPLAYING,
        )
        self._store.save_event(replay_evt)

        return RecoveryDecision(
            run_id=plan.run_id, action=plan.suggested_action, success=True,
            resumed_at=datetime.now(timezone.utc),
            new_status=RunStatus.REPLAYING,
            message="Replay initiated",
        )

    async def _handle_cancel(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        new_state, evt = self._state_machine.cancel(state)
        self._store.save_run_state(new_state)
        self._store.save_event(evt)
        return RecoveryDecision(
            run_id=plan.run_id, action=plan.suggested_action, success=True,
            new_status=RunStatus.CANCELLED, message="Run cancelled",
        )

    async def _handle_escalate(
        self, state: PipelineRunState, plan: RecoveryPlan,
        orchestrator, on_decision, run_fn, timeout_s,
    ) -> RecoveryDecision:
        return RecoveryDecision(
            run_id=plan.run_id, action=plan.suggested_action, success=False,
            message="Escalation — manual intervention required",
        )

    # ── Crash Recovery ─────────────────────────────────────────

    async def crash_recovery(
        self, run_id: str, orchestrator=None, timeout_s: int = 3600,
    ) -> RecoveryDecision:
        """Crash recovery 入口"""
        run_state = self.analyse(run_id)
        if not run_state:
            return RecoveryDecision(
                run_id=run_id, action=RecoveryAction.RESTART_RUN, success=False,
                message=f"Run {run_id} not found",
            )

        if run_state.status.terminal:
            return RecoveryDecision(
                run_id=run_id, action=RecoveryAction.REPLAY_RUN, success=True,
                message=f"Run already terminal: {run_state.status.value}",
            )

        plan = self.build_recovery_plan(run_state)
        return await self.execute_recovery(plan, orchestrator=orchestrator, timeout_s=timeout_s)

    def list_unfinished_runs(self) -> list[PipelineRunState]:
        """列出所有未完成的 runs"""
        result: list[PipelineRunState] = []
        return result
