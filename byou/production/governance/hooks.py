"""Byou L3 HITL — Pipeline Hooks。

注入 Orchestrator 的暂停/恢复机制:
- 每个 stage 前后检查是否需要审批
- 如需审批 → 返回 HALT 信号
- 外部决策到达 → resume pipeline
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Optional

from .engine import ApprovalEngine, APPROVAL_HALT
from .types import (
    ApprovalChannel,
    ApprovalContext,
    ApprovalDecision,
    ApprovalMode,
    ApprovalRequest,
    ApprovalStatus,
)

logger = logging.getLogger(__name__)


class PipelineHooks:
    """审批挂载管线钩子。

    注入方式:
        hooks = PipelineHooks(engine)
        hooks.install(orchestrator)

    每个 stage 执行前:
        result = hooks.before_stage("strategy", context)
        if result == APPROVAL_HALT:
            return  # 暂停
    """

    def __init__(
        self,
        engine: ApprovalEngine,
        default_channel: ApprovalChannel = ApprovalChannel.WEBCHAT,
        max_retries: int = 3,
    ):
        self._engine = engine
        self._default_channel = default_channel
        self._max_retries = max_retries

        # 暂停恢复机制
        self._paused: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._pending_requests: dict[str, ApprovalRequest] = {}

    # ── Stage 前后钩子 ──────────────────────────────────────────

    def before_stage(
        self,
        stage: str,
        pipeline_id: str,
        action: str = "",
        tool_name: str = "",
        capability: str = "",
        agent: str = "",
        risk_level: str = "medium",
        **extra,
    ) -> ApprovalRequest | str:
        """Stage 执行前检查。

        Returns:
            ApprovalRequest — 需要暂停 (DEMAND / HUMAN_REQUIRED)
            str APPROVAL_HALT — 同上, 兼容信号
            ApprovalRequest (APPROVED/AUTO) — 可继续
        """
        context = ApprovalContext(
            pipeline_id=pipeline_id,
            stage=stage,
            agent=agent,
            tool_name=tool_name,
            capability=capability,
            action=action or f"{stage}_execute",
            risk_level=risk_level,
        )
        request = self._engine.check(context, channel=self._default_channel)

        if request.mode in (ApprovalMode.DEMAND, ApprovalMode.HUMAN_REQUIRED):
            self._pending_requests[request.id] = request
            logger.info(
                "PipelineHooks: HALT at stage=%s action=%s request=%s mode=%s",
                stage, action, request.id, request.mode.value,
            )
            return request
        return request  # AUTO / DEFER → 放行

    def after_stage(
        self,
        stage: str,
        pipeline_id: str,
        success: bool,
    ) -> None:
        """Stage 执行后回调 (当前仅日志, 后续可扩展事后审计)"""
        if success:
            logger.debug("PipelineHooks: stage=%s pipeline=%s OK", stage, pipeline_id)
        else:
            logger.warning("PipelineHooks: stage=%s pipeline=%s FAILED", stage, pipeline_id)

    # ── 暂停/恢复 ───────────────────────────────────────────────

    async def pause_pipeline(
        self,
        request: ApprovalRequest,
        timeout_s: int | None = None,
    ) -> ApprovalDecision:
        """暂停 pipeline 并等待审批决策"""
        event = asyncio.Event()
        self._paused[request.id] = event

        try:
            decision = await self._engine.wait_for_decision(request, timeout_s=timeout_s)
            self._decisions[request.id] = decision
            event.set()
            return decision
        except Exception as exc:
            logger.exception("PipelineHooks: pause error for %s: %s", request.id, exc)
            raise

    def resume(self, request_id: str, decision: ApprovalDecision) -> ApprovalRequest | None:
        """恢复被暂停的 pipeline (外部决策到达时调用)"""
        self._decisions[request_id] = decision
        req = self._engine.decide(request_id, decision)
        if req is None:
            return None

        event = self._paused.pop(request_id, None)
        if event:
            event.set()
        return req

    def get_decision(self, request_id: str) -> ApprovalDecision | None:
        return self._decisions.get(request_id)

    def clear_pipeline(self, pipeline_id: str) -> None:
        """清理 pipeline 的待审批项"""
        to_remove = [
            rid for rid, req in self._pending_requests.items()
            if req.pipeline_id == pipeline_id
        ]
        for rid in to_remove:
            self._pending_requests.pop(rid, None)
            self._paused.pop(rid, None)
            self._decisions.pop(rid, None)
