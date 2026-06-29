"""Byou L4 — 恢复/回放/重跑 报告生成。

生成结构化报告:
- RecoveryReport: 恢复结果
- ReplayDiffReport: 重放差异
- RunSummaryReport: 运行摘要
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from .types import (
    PipelineRunState,
    RecoveryAction,
    RecoveryDecision,
    ReplayResult,
    RerunResult,
    RunLifecycleEvent,
    RunStatus,
)


class RecoveryReport(BaseModel):
    """恢复报告"""
    run_id: str
    action: RecoveryAction
    success: bool
    original_status: RunStatus | None = None
    new_status: RunStatus | None = None
    message: str = ""
    duration_ms: float = 0.0
    retry_count: int = 0
    checkpoints_available: int = 0
    checkpoint_used: str | None = None
    error: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_decision(cls, decision: RecoveryDecision, retry_count: int = 0) -> "RecoveryReport":
        return cls(
            run_id=decision.run_id,
            action=decision.action,
            success=decision.success,
            new_status=decision.new_status,
            message=decision.message,
            duration_ms=decision.duration_ms,
            retry_count=retry_count,
        )


class ReplayDiffReport(BaseModel):
    """重放差异报告"""
    original_run_id: str
    compare_run_id: str
    total_stages: int = 0
    matched_stages: int = 0
    divergent_stages: int = 0
    divergence_details: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_replay(cls, result: ReplayResult) -> "ReplayDiffReport":
        return cls(
            original_run_id=result.original_run_id,
            compare_run_id=result.request.compare_with or "N/A",
            total_stages=result.stages_replayed,
            matched_stages=result.stages_passed,
            divergent_stages=result.stages_diverged,
            divergence_details=result.divergence_details,
        )


class RerunReport(BaseModel):
    """重跑报告"""
    original_run_id: str
    new_run_id: str
    from_stage: str
    success: bool
    reused_stages: list[str] = Field(default_factory=list)
    reran_stages: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_rerun(cls, result: RerunResult, from_stage: str, original_run_id: str) -> "RerunReport":
        return cls(
            original_run_id=original_run_id,
            new_run_id=result.new_run_id,
            from_stage=from_stage,
            success=result.success,
            reused_stages=result.reused_stages,
            reran_stages=result.reran_stages,
            errors=result.errors,
        )


class RunSummaryReport(BaseModel):
    """单次运行摘要"""
    run_id: str
    status: str
    stages_total: int = 0
    stages_completed: int = 0
    stages_failed: int = 0
    stages_skipped: int = 0
    total_checkpoints: int = 0
    total_events: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float = 0.0
    message: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def build_run_summary(
    run_state: PipelineRunState | None,
    checkpoint_count: int = 0,
    event_count: int = 0,
) -> RunSummaryReport:
    """从 run state 构建摘要"""
    if not run_state:
        return RunSummaryReport(run_id="unknown", status="not_found", message="Run not found")

    return RunSummaryReport(
        run_id=run_state.run_id,
        status=run_state.status.value,
        total_checkpoints=checkpoint_count,
        total_events=event_count,
        started_at=run_state.started_at.isoformat() if run_state.started_at else None,
        completed_at=run_state.completed_at.isoformat() if run_state.completed_at else None,
        duration_ms=run_state.total_duration_ms,
        message=run_state.error_message or run_state.pause_reason or "",
    )
