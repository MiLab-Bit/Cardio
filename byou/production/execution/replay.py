"""Byou L4 — 历史运行回放。

Replay 模式:
1. 加载历史 run 的 checkpoints
2. 重建各 stage 的输入/输出
3. 生成 divergence report (对比两次 run 的差异)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .checkpoints import CheckpointManager, build_recovery_payload
from .storage import BaseStorage
from .types import (
    CheckpointRecord,
    PipelineRunState,
    ReplayRequest,
    ReplayResult,
    RunStatus,
)

logger = logging.getLogger(__name__)


class ReplayEngine:
    """回放引擎 — 分析历史运行"""

    def __init__(self, storage: BaseStorage):
        self._store = storage
        self._checkpoints = CheckpointManager(storage)

    async def replay(self, request: ReplayRequest) -> ReplayResult:
        """执行回放"""
        run_state = self._store.load_run_state(request.run_id)
        if not run_state:
            return ReplayResult(
                request=request, success=False,
                original_run_id=request.run_id,
                errors=[f"Run {request.run_id} not found"],
            )

        # 载入所有 checkpoints
        cps = self._checkpoints.list_run_checkpoints(request.run_id)
        if not cps:
            return ReplayResult(
                request=request, success=False,
                original_run_id=request.run_id,
                errors=["No checkpoints available for replay"],
            )

        # 过滤 stage checkpoints
        stage_cps = [c for c in cps if c.step is None and c.stage != "pause"]

        # 按 stage 顺序排列
        stage_order = ["extraction", "research", "synthesis", "strategy", "critique"]
        ordered: list[CheckpointRecord] = []
        for stage in stage_order:
            for cp in stage_cps:
                if cp.stage == stage:
                    ordered.append(cp)
                    break

        # 如果指定 from_stage, 截断
        if request.from_stage:
            start_idx = 0
            for i, cp in enumerate(ordered):
                if cp.stage == request.from_stage:
                    start_idx = i
                    break
            ordered = ordered[start_idx:]

        # 构建回放结果
        replayed_id = None
        stages_replayed = len(ordered)
        stages_passed = 0
        stages_failed = 0
        divergences: list[dict[str, Any]] = []

        if not request.dry_run:
            # 在非 dry-run 模式下才执行实际回放
            # 目前只做分析
            pass

        # 统计
        for cp in ordered:
            if cp.status.value == "success":
                stages_passed += 1
            else:
                stages_failed += 1

        # 对比分析 (如果有 compare_with)
        if request.compare_with:
            compare_cps = self._checkpoints.list_run_checkpoints(request.compare_with)
            if compare_cps:
                divergences = self._compare_runs(ordered, compare_cps)

        return ReplayResult(
            request=request,
            success=True,
            original_run_id=request.run_id,
            replayed_run_id=replayed_id,
            stages_replayed=stages_replayed,
            stages_passed=stages_passed,
            stages_failed=stages_failed,
            stages_diverged=len(divergences),
            divergence_details=divergences,
        )

    def _compare_runs(
        self,
        run_a: list[CheckpointRecord],
        cps_b: list[CheckpointRecord],
    ) -> list[dict[str, Any]]:
        """对比两次运行的检查点差异"""
        divergences: list[dict[str, Any]] = []

        # Build stage → checkpoint map for comparison
        b_map: dict[str, CheckpointRecord] = {}
        for cp in cps_b:
            if cp.step is None:
                b_map[cp.stage] = cp

        for cp_a in run_a:
            b = b_map.get(cp_a.stage)
            if not b:
                divergences.append({
                    "stage": cp_a.stage,
                    "type": "missing_in_compare",
                    "detail": f"Stage {cp_a.stage} missing in comparison run",
                })
                continue

            # Compare output snapshots
            a_out = cp_a.output_snapshot
            b_out = b.output_snapshot
            if a_out and b_out:
                a_keys = set(a_out.keys())
                b_keys = set(b_out.keys())
                missing = a_keys - b_keys
                extra = b_keys - a_keys
                if missing or extra:
                    divergences.append({
                        "stage": cp_a.stage,
                        "type": "output_diff",
                        "detail": f"Output keys differ: missing={missing}, extra={extra}",
                    })

        return divergences

    def get_replay_summary(self, run_id: str) -> dict[str, Any]:
        """获取运行的回放摘要"""
        cps = self._checkpoints.list_run_checkpoints(run_id)
        run_state = self._store.load_run_state(run_id)

        return {
            "run_id": run_id,
            "status": run_state.status.value if run_state else "unknown",
            "stage_count": len(set(c.stage for c in cps if c.step is None)),
            "checkpoint_count": len(cps),
            "stages": [{
                "stage": c.stage,
                "status": c.status.value,
                "checkpoint_at": c.checkpoint_at.isoformat() if c.checkpoint_at else None,
                "resumable": c.resumable,
            } for c in cps if c.step is None],
        }
