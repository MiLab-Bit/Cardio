"""Byou L4 — 从中间 step 重跑。

支持:
- 复用前面成功的 stage 结果
- 从指定 stage 开始重新执行
- 保留原始 run_id 用于 trace
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .checkpoints import CheckpointManager, build_recovery_payload
from .idempotency import IdempotencyGuard, generate_replay_safe_key
from .storage import BaseStorage
from .types import (
    CheckpointRecord,
    PipelineRunState,
    RerunRequest,
    RerunResult,
    RunLifecycleEvent,
    RunStatus,
)

logger = logging.getLogger(__name__)

# Pipeline stage order
_STAGE_ORDER: list[str] = ["extraction", "research", "synthesis", "strategy", "critique"]


class RerunEngine:
    """Stage 重跑引擎"""

    def __init__(self, storage: BaseStorage):
        self._store = storage
        self._checkpoints = CheckpointManager(storage)
        self._idempotency = IdempotencyGuard(storage)

    async def rerun(
        self,
        request: RerunRequest,
        *,
        orchestrator=None,    # Orchestrator 实例
        run_fn=None,          # 用户提供的执行函数
    ) -> RerunResult:
        """从指定 stage 重跑 pipeline。

        Args:
            request: 重跑请求
            orchestrator: Orchestrator 实例 (用于执行 stage)
            run_fn: async run_fn(stage_name, ctx_snapshot) → PipelineContext

        Returns:
            RerunResult
        """
        original = self._store.load_run_state(request.run_id)
        if not original:
            return RerunResult(
                request=request, success=False, new_run_id="",
                errors=[f"Original run {request.run_id} not found"],
            )

        # 确定 from_stage 在 pipeline 中的位置
        try:
            from_index = _STAGE_ORDER.index(request.from_stage)
        except ValueError:
            return RerunResult(
                request=request, success=False, new_run_id="",
                errors=[f"Unknown stage: {request.from_stage}"],
            )

        # 收集可复用的 stage 结果
        reused_stages: list[str] = []
        reran_stages: list[str] = _STAGE_ORDER[from_index:]

        if request.reuse_checkpoints:
            cps = self._checkpoints.list_run_checkpoints(request.run_id)
            for stage in _STAGE_ORDER[:from_index]:
                for cp in reversed(cps):
                    if cp.stage == stage and cp.status.value == "success" and cp.resumable:
                        reused_stages.append(stage)
                        break

        # 生成新 run_id (rerun 产生新 run)
        from uuid import uuid4
        new_run_id = uuid4().hex[:12]

        # 收集复用结果
        reused_context: dict[str, Any] = {}
        if request.reuse_checkpoints and reused_stages:
            # Load context from last reused stage checkpoint
            last_reused = reused_stages[-1]
            last_cp = self._checkpoints.get_stage_checkpoint(request.run_id, last_reused)
            if last_cp:
                reused_context = last_cp.output_snapshot

        # 创建新的 run state
        new_state = PipelineRunState(
            run_id=new_run_id,
            trace_id=uuid4().hex[:16],
            status=RunStatus.PENDING,
            card_image_path=original.card_image_path,
            audio_file_path=original.audio_file_path,
            extra_context={
                **original.extra_context,
                "rerun_from": request.run_id,
                "rerun_stage": request.from_stage,
                "reused_stages": reused_stages,
                **reused_context,
            },
            tags={**original.tags, "rerun_from": request.run_id},
        )
        self._store.save_run_state(new_state)

        # Log event
        evt = RunLifecycleEvent(
            run_id=new_run_id, event_type="rerun_initiated",
            to_status=RunStatus.PENDING,
            details={
                "original_run_id": request.run_id,
                "from_stage": request.from_stage,
                "reused_stages": reused_stages,
                "reran_stages": reran_stages,
            },
        )
        self._store.save_event(evt)

        logger.info("Rerun initiated: original=%s new=%s from_stage=%s reused=%s reran=%s",
                     request.run_id, new_run_id, request.from_stage, reused_stages, reran_stages)

        return RerunResult(
            request=request,
            success=True,
            new_run_id=new_run_id,
            reused_stages=reused_stages,
            reran_stages=reran_stages,
        )

    def get_stage_order(self, stage: str) -> int:
        """获取 stage 在 pipeline 中的位置"""
        try:
            return _STAGE_ORDER.index(stage)
        except ValueError:
            return -1

    def get_remaining_stages(self, from_stage: str) -> list[str]:
        """获取从 from_stage 开始的剩余 stages"""
        try:
            idx = _STAGE_ORDER.index(from_stage)
            return _STAGE_ORDER[idx:]
        except ValueError:
            return list(_STAGE_ORDER)
