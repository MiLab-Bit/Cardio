"""Byou L4 — Run / Stage 状态机。

管理 PipelineRunState 的生命周期转换。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .types import (
    PipelineRunState,
    RecoveryAction,
    RunLifecycleEvent,
    RunStatus,
    StageExecStatus,
    StageExecutionState,
)

logger = logging.getLogger(__name__)

# ── 合法状态转换表 ─────────────────────────────────────────────

_RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING:        {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING:        {RunStatus.PAUSED, RunStatus.WAITING_SIGNAL, RunStatus.RETRYING,
                                RunStatus.FAILED, RunStatus.COMPLETED, RunStatus.CANCELLED},
    RunStatus.PAUSED:         {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.WAITING_SIGNAL: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RETRYING:       {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.FAILED:         {RunStatus.RETRYING, RunStatus.REPLAYING, RunStatus.CANCELLED},
    RunStatus.COMPLETED:      {RunStatus.REPLAYING},
    RunStatus.CANCELLED:      set(),
    RunStatus.REPLAYING:      {RunStatus.COMPLETED, RunStatus.FAILED},
}

_STAGE_TRANSITIONS: dict[StageExecStatus, set[StageExecStatus]] = {
    StageExecStatus.PENDING:  {StageExecStatus.RUNNING, StageExecStatus.SKIPPED},
    StageExecStatus.RUNNING:  {StageExecStatus.SUCCESS, StageExecStatus.FAILED, StageExecStatus.PAUSED},
    StageExecStatus.PAUSED:   {StageExecStatus.RUNNING, StageExecStatus.FAILED, StageExecStatus.SKIPPED},
    StageExecStatus.FAILED:   {StageExecStatus.RETRYING, StageExecStatus.SKIPPED},
    StageExecStatus.RETRYING: {StageExecStatus.SUCCESS, StageExecStatus.FAILED},
    StageExecStatus.SUCCESS:  set(),
    StageExecStatus.SKIPPED:  set(),
}


class RunStateMachine:
    """Pipeline Run 状态机 — 纯函数无副作用"""

    # Each transition method returns (bool, str) → (allowed, error_message)

    @staticmethod
    def transition(state: PipelineRunState, to: RunStatus) -> tuple[bool, str]:
        allowed = _RUN_TRANSITIONS.get(state.status, set())
        if to not in allowed:
            return False, f"Invalid transition: {state.status.value} → {to.value}"
        return True, ""

    @staticmethod
    def start(state: PipelineRunState) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.RUNNING
        state.started_at = datetime.now(timezone.utc)
        state.last_heartbeat = state.started_at
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="started",
            from_status=RunStatus.PENDING, to_status=RunStatus.RUNNING,
        )
        return state, evt

    @staticmethod
    def pause(
        state: PipelineRunState,
        reason: str = "",
        approval_request_id: str | None = None,
    ) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.PAUSED
        state.paused_at = datetime.now(timezone.utc)
        state.pause_reason = reason
        if approval_request_id:
            state.approval_request_id = approval_request_id
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="paused",
            from_status=RunStatus.RUNNING, to_status=RunStatus.PAUSED,
            details={"reason": reason},
        )
        return state, evt

    @staticmethod
    def resume(state: PipelineRunState) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.RUNNING
        state.resumed_at = datetime.now(timezone.utc)
        state.pause_reason = None
        state.approval_request_id = None
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="resumed",
            from_status=RunStatus.PAUSED, to_status=RunStatus.RUNNING,
        )
        return state, evt

    @staticmethod
    def complete(state: PipelineRunState) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.COMPLETED
        state.completed_at = datetime.now(timezone.utc)
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="completed",
            from_status=RunStatus.RUNNING, to_status=RunStatus.COMPLETED,
        )
        return state, evt

    @staticmethod
    def fail(state: PipelineRunState, error: str) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.FAILED
        state.error_message = error
        state.completed_at = datetime.now(timezone.utc)
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="failed",
            from_status=RunStatus.RUNNING, to_status=RunStatus.FAILED,
            details={"error": error},
        )
        return state, evt

    @staticmethod
    def retry(state: PipelineRunState) -> tuple[PipelineRunState | None, RunLifecycleEvent | None, str]:
        """Retry a failed run. Returns (new_state, event, error_msg)."""
        if state.retry_count >= state.max_retries:
            return None, None, f"Max retries ({state.max_retries}) exceeded"
        state.status = RunStatus.RETRYING
        state.retry_count += 1
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="retrying",
            from_status=RunStatus.FAILED, to_status=RunStatus.RETRYING,
            details={"attempt": state.retry_count, "max": state.max_retries},
        )
        return state, evt, ""

    @staticmethod
    def cancel(state: PipelineRunState) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.CANCELLED
        state.completed_at = datetime.now(timezone.utc)
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="cancelled",
            from_status=RunStatus.RUNNING, to_status=RunStatus.CANCELLED,
        )
        return state, evt

    @staticmethod
    def wait_signal(
        state: PipelineRunState, reason: str = ""
    ) -> tuple[PipelineRunState, RunLifecycleEvent]:
        state.status = RunStatus.WAITING_SIGNAL
        state.paused_at = datetime.now(timezone.utc)
        state.pause_reason = reason
        evt = RunLifecycleEvent(
            run_id=state.run_id, event_type="waiting_signal",
            from_status=RunStatus.RUNNING, to_status=RunStatus.WAITING_SIGNAL,
            details={"reason": reason},
        )
        return state, evt

    @staticmethod
    def heartbeat(state: PipelineRunState) -> PipelineRunState:
        state.last_heartbeat = datetime.now(timezone.utc)
        return state


class StageStateMachine:
    """Stage 执行状态机"""

    @staticmethod
    def transition(s: StageExecutionState, to: StageExecStatus) -> tuple[bool, str]:
        allowed = _STAGE_TRANSITIONS.get(s.status, set())
        if to not in allowed:
            return False, f"Invalid stage transition: {s.status.value} → {to.value}"
        return True, ""

    @staticmethod
    def start(s: StageExecutionState) -> StageExecutionState:
        s.status = StageExecStatus.RUNNING
        s.started_at = datetime.now(timezone.utc)
        return s

    @staticmethod
    def succeed(s: StageExecutionState) -> StageExecutionState:
        s.status = StageExecStatus.SUCCESS
        s.completed_at = datetime.now(timezone.utc)
        if s.started_at:
            s.duration_ms = (s.completed_at - s.started_at).total_seconds() * 1000
        return s

    @staticmethod
    def fail(s: StageExecutionState, error: str) -> StageExecutionState:
        s.status = StageExecStatus.FAILED
        s.error = error
        s.completed_at = datetime.now(timezone.utc)
        if s.started_at:
            s.duration_ms = (s.completed_at - s.started_at).total_seconds() * 1000
        return s

    @staticmethod
    def retry(s: StageExecutionState) -> StageExecutionState | None:
        if s.retry_count >= s.max_retries:
            return None
        s.status = StageExecStatus.RETRYING
        s.retry_count += 1
        return s

    @staticmethod
    def pause(s: StageExecutionState) -> StageExecutionState:
        s.status = StageExecStatus.PAUSED
        return s

    @staticmethod
    def skip(s: StageExecutionState) -> StageExecutionState:
        s.status = StageExecStatus.SKIPPED
        return s


# ── Recovery 决策映射 ──────────────────────────────────────────


# 每种 RunStatus 在 crash/restart 时的默认 RecoveryAction
RECOVERY_ACTION_MAP: dict[RunStatus, RecoveryAction] = {
    RunStatus.PENDING:        RecoveryAction.RESTART_RUN,
    RunStatus.RUNNING:        RecoveryAction.RETRY_STAGE,    # crash during execution → retry current stage
    RunStatus.PAUSED:         RecoveryAction.RESUME_RUN,     # 审批等待 → resume
    RunStatus.WAITING_SIGNAL: RecoveryAction.RESUME_RUN,
    RunStatus.RETRYING:       RecoveryAction.RETRY_STAGE,
    RunStatus.FAILED:         RecoveryAction.RERUN_FROM_STAGE,
    RunStatus.COMPLETED:      RecoveryAction.REPLAY_RUN,
    RunStatus.CANCELLED:      RecoveryAction.RESTART_RUN,
    RunStatus.REPLAYING:      RecoveryAction.RESUME_RUN,
}
