"""Byou L4 — Checkpoint 写入与读取。

Checkpoint 策略:
- Stage 级: extraction/research/synthesis/strategy/critique 完成后
- 子步骤级: enrichment/browser 完成后 (高成本, 失败后不想从头跑)
- 审批暂停点: pause 前
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .storage import BaseStorage
from .types import (
    CheckpointRecord,
    PipelineRunState,
    RunStatus,
    StageExecStatus,
    StageExecutionState,
)

logger = logging.getLogger(__name__)

# ── 必须 checkpoint 的 stage ───────────────────────────────────

_STAGE_CHECKPOINT_REQUIRED: set[str] = {
    "extraction",
    "research",
    "synthesis",
    "strategy",
    "critique",
}

# ── 必须 checkpoint 的子步骤 ───────────────────────────────────

_SUBSTEP_CHECKPOINT_REQUIRED: set[str] = {
    "enrichment",       # 多源 API 调用, 昂贵且不可重复
    "browser",          # 浏览器操作, 高成本
    "synthesis_inner",  # LLM synthesis, token 成本
}


class CheckpointManager:
    """Checkpoint 读写管理器"""

    def __init__(self, storage: BaseStorage):
        self._store = storage

    # ── Write ──────────────────────────────────────────────────

    def checkpoint_stage(
        self,
        run_id: str,
        trace_id: str,
        stage_name: str,
        stage_state: StageExecutionState,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        agent_name: str = "",
    ) -> CheckpointRecord:
        """为 stage 完成创建 checkpoint"""
        cp = CheckpointRecord(
            run_id=run_id,
            trace_id=trace_id,
            stage=stage_name,
            step=None,
            status=stage_state.status,
            agent_name=agent_name or stage_state.agent_name,
            input_snapshot=input_data or {},
            output_snapshot=output_data or {},
            retry_count=stage_state.retry_count,
            resumable=stage_state.status == StageExecStatus.SUCCESS,
        )
        self._store.save_checkpoint(cp)

        # 关联到 stage state
        stage_state.checkpoint_ids.append(cp.checkpoint_id)
        self._store.save_stage_state(stage_state)

        logger.debug("Checkpoint: run=%s stage=%s cp=%s resumable=%s",
                      run_id, stage_name, cp.checkpoint_id, cp.resumable)
        return cp

    def checkpoint_substep(
        self,
        run_id: str,
        trace_id: str,
        stage_name: str,
        step_name: str,
        status: StageExecStatus,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
    ) -> CheckpointRecord:
        """为 stage 内子步骤创建 checkpoint"""
        cp = CheckpointRecord(
            run_id=run_id,
            trace_id=trace_id,
            stage=stage_name,
            step=step_name,
            status=status,
            input_snapshot=input_data or {},
            output_snapshot=output_data or {},
            resumable=status == StageExecStatus.SUCCESS,
        )
        self._store.save_checkpoint(cp)
        logger.debug("Checkpoint substep: run=%s stage=%s step=%s cp=%s",
                      run_id, stage_name, step_name, cp.checkpoint_id)
        return cp

    def checkpoint_pause(
        self,
        run_id: str,
        trace_id: str,
        stage_name: str,
        pause_reason: str,
        ctx_snapshot: dict[str, Any] | None = None,
    ) -> CheckpointRecord:
        """在暂停前 checkpoint — 记录暂停位置"""
        cp = CheckpointRecord(
            run_id=run_id,
            trace_id=trace_id,
            stage=stage_name,
            step="pause",
            status=StageExecStatus.PAUSED,
            input_snapshot=ctx_snapshot or {},
            extra={"pause_reason": pause_reason},
            resumable=True,
        )
        self._store.save_checkpoint(cp)
        logger.info("Checkpoint pause: run=%s stage=%s cp=%s reason=%s",
                     run_id, stage_name, cp.checkpoint_id, pause_reason)
        return cp

    # ── Read ───────────────────────────────────────────────────

    def get_latest_checkpoint(self, run_id: str) -> CheckpointRecord | None:
        """获取 run 的最新 checkpoint"""
        cps = self._store.list_checkpoints(run_id)
        return cps[-1] if cps else None

    def get_latest_resumable(self, run_id: str) -> CheckpointRecord | None:
        """获取 run 最新可恢复的 checkpoint"""
        cps = self._store.list_checkpoints(run_id)
        for cp in reversed(cps):  # noqa: B007 — loop var used in body
            if cp.resumable:
                return cp
        return None

    def get_stage_checkpoint(self, run_id: str, stage: str) -> CheckpointRecord | None:
        """获取指定 stage 的 checkpoint (最新的)"""
        cps = self._store.list_checkpoints(run_id)
        for cp in reversed(cps):
            if cp.stage == stage and cp.step is None:
                return cp
        return None

    def list_run_checkpoints(self, run_id: str) -> list[CheckpointRecord]:
        return self._store.list_checkpoints(run_id)

    # ── Should-checkpoint helpers ──────────────────────────────

    @staticmethod
    def stage_needs_checkpoint(stage_name: str) -> bool:
        """判断 stage 是否需要 checkpoint"""
        return stage_name in _STAGE_CHECKPOINT_REQUIRED

    @staticmethod
    def substep_needs_checkpoint(step_name: str) -> bool:
        """判断子步骤是否需要 checkpoint"""
        return step_name in _SUBSTEP_CHECKPOINT_REQUIRED


# ── Checkpoint-driven Pipeline Recovery ───────────────────────


def build_recovery_payload(
    checkpoints: CheckpointManager,
    run_state: PipelineRunState,
) -> dict[str, Any] | None:
    """基于 checkpoint 构建恢复上下文。

    返回 None 表示无法恢复 (需从头跑)。
    返回 dict 包含恢复点信息。
    """
    run_id = run_state.run_id

    # 找到最新可恢复 checkpoint
    latest_cp = checkpoints.get_latest_resumable(run_id)

    if not latest_cp:
        # 尝试从有 stage 结果的 checkpoint 恢复
        all_cps = checkpoints.list_run_checkpoints(run_id)
        if not all_cps:
            logger.warning("No checkpoints for run=%s — cannot recover", run_id)
            return None

        # 回退到最后一个成功的 stage checkpoint
        for cp in reversed(all_cps):
            if cp.status == StageExecStatus.SUCCESS and cp.step is None:
                latest_cp = cp
                break

        if not latest_cp:
            return None

    # 收集所有已完成 stage 的输出
    completed_stages: dict[str, dict[str, Any]] = {}
    cps = checkpoints.list_run_checkpoints(run_id)
    for cp in cps:
        if cp.status == StageExecStatus.SUCCESS and cp.resumable and cp.step is None:
            completed_stages[cp.stage] = cp.output_snapshot

    return {
        "from_stage": latest_cp.stage,
        "from_step": latest_cp.step,
        "checkpoint_id": latest_cp.checkpoint_id,
        "completed_stages": completed_stages,
        "ctx_snapshot": latest_cp.input_snapshot,
    }
