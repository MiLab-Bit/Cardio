"""Byou L3 HITL — 审批引擎。

核心逻辑: 接收 context → 定策略 → 创建请求 → 返回 pipeline block 信号
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .policy import ApprovalPolicyEngine
from .store import ApprovalStore
from .types import (
    ApprovalChannel,
    ApprovalContext,
    ApprovalDecision,
    ApprovalMode,
    ApprovalNotification,
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
)

logger = logging.getLogger(__name__)

# 阻塞信号
APPROVAL_HALT = "__APPROVAL_HALT__"


class ApprovalEngine:
    """审批引擎 — 接收审查请求, 决定是放行还是阻塞 pipeline

    用法:
        eng = ApprovalEngine(store=...)
        result = eng.check(context)
        if result.mode in (ApprovalMode.DEMAND, ApprovalMode.HUMAN_REQUIRED):
            # 暂停 pipeline, 等待 decision
            await eng.wait_for_decision(blocked_request)
    """

    def __init__(
        self,
        store: ApprovalStore,
        policy_engine: ApprovalPolicyEngine | None = None,
        default_channel: ApprovalChannel = ApprovalChannel.WEBCHAT,
    ):
        self._store = store
        self._policy = policy_engine or ApprovalPolicyEngine()
        self._default_channel = default_channel
        self._pending_futures: dict[str, asyncio.Future] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    # ── 入站: 检查是否需要审批 ─────────────────────────────────

    def check(
        self,
        context: ApprovalContext,
        channel: ApprovalChannel | None = None,
    ) -> ApprovalRequest:
        """检查指定上下文是否需要审批。

        返回 ApprovalRequest, 调用方检查:
        - request.mode == AUTO → 可直接执行
        - request.mode == DEFER → 执行 + 事后审查
        - request.mode == DEMAND / HUMAN_REQUIRED → 暂停 pipeline
        """
        rule = self._policy.match(context)
        request = ApprovalRequest(
            pipeline_id=context.pipeline_id,
            scope=ApprovalScope.ACTION,
            mode=rule.approval_mode,
            context=context,
            message=f"Stage '{context.stage}': {context.action}\n"
                    f"Risk: {context.risk_level}, Agent: {context.agent}",
            timeout_s=rule.timeout_s,
            max_approvals=rule.max_approvals,
            escalation=rule.escalation,
        )

        if request.mode in (ApprovalMode.AUTO, ApprovalMode.DEFER):
            # 自动通行 / 延迟审查: 立即 resolve 为 auto_approved
            request.status = ApprovalStatus.AUTO_APPROVED
        # DEMAND / HUMAN_REQUIRED: 保持 PENDING, 进入队列

        self._store.create(request)
        logger.debug(
            "ApprovalEngine.check: action=%s mode=%s status=%s",
            context.action, request.mode.value, request.status.value,
        )
        return request

    # ── 阻塞等待 ────────────────────────────────────────────────

    async def wait_for_decision(
        self,
        request: ApprovalRequest,
        timeout_s: int | None = None,
    ) -> ApprovalDecision:
        """阻塞等待审批决策。超时返回过期/拒绝决策。

        外部调用此方法暂停 pipeline, 直到收到决策或超时。
        """
        if request.status == ApprovalStatus.AUTO_APPROVED:
            return ApprovalDecision(approved=True, reason="auto_approved")

        timeout = timeout_s or request.timeout_s
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_futures[request.id] = future

        try:
            decision = await asyncio.wait_for(future, timeout=timeout)
            return decision
        except asyncio.TimeoutError:
            logger.warning("ApprovalEngine: request %s timed out after %ds", request.id, timeout)
            self._store.expire(request.id)
            self._pending_futures.pop(request.id, None)
            return ApprovalDecision(
                approved=request.escalation == "auto_approve",
                reason=f"timeout after {timeout}s",
            )
        except Exception as exc:
            logger.exception("ApprovalEngine: wait error for %s: %s", request.id, exc)
            self._pending_futures.pop(request.id, None)
            raise

    # ── 出站: 接收决策 ──────────────────────────────────────────

    def decide(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> ApprovalRequest | None:
        """接收外部决策 (来自 webchat/API/webhook)"""
        req = self._store.resolve(request_id, decision)
        if req is None:
            return None

        # 唤醒等待者
        future = self._pending_futures.pop(request_id, None)
        if future and not future.done():
            future.set_result(decision)

        return req

    # ── 通知生成 ────────────────────────────────────────────────

    def build_notification(
        self,
        request: ApprovalRequest,
        channel: ApprovalChannel | None = None,
    ) -> ApprovalNotification:
        ch = channel or self._default_channel
        return ApprovalNotification(
            request_id=request.id,
            channel=ch,
            title=f"Approval required: {request.context.action}",
            body=request.message or f"Pipeline {request.pipeline_id} needs approval",
            actions=["approve", "reject"],
        )

    # ── 超时巡检 ────────────────────────────────────────────────

    async def poll_expired(self) -> int:
        """巡检过期项并将决策推送给等待者"""
        count = await self._store.expire_overdue()
        # 过期请求如果有等待者, 发送拒绝信号
        for req in self._store.list_all():
            if req.status in (ApprovalStatus.EXPIRED, ApprovalStatus.ESCALATED):
                future = self._pending_futures.get(req.id)
                if future and not future.done():
                    future.set_result(ApprovalDecision(
                        approved=False,
                        reason=f"expired: {req.status.value}",
                    ))
        return count
