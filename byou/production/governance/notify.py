"""Byou L3 HITL — 通知分发。

统一通知出口: 根据 channel 分发到不同渲染器。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .broker import ApprovalBroker
from .types import (
    ApprovalChannel,
    ApprovalNotification,
    ApprovalRequest,
)

logger = logging.getLogger(__name__)

# ── 每个通道的渲染钩子 ──

ChannelRenderer = Callable[[ApprovalRequest], str]  # 返回人类可读文本


class NotificationDispatcher:
    """通知分发器 — 根据通道渲染消息 + 发送

    预登记 → rendering pipeline → broker.send()
    """

    def __init__(self, broker: ApprovalBroker):
        self._broker = broker
        self._renderers: dict[ApprovalChannel, ChannelRenderer] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """预登记默认渲染器"""
        self._renderers[ApprovalChannel.WEBCHAT] = self._render_webchat
        self._renderers[ApprovalChannel.API] = self._render_api
        self._renderers[ApprovalChannel.EMAIL] = self._render_email

    def register_renderer(self, channel: ApprovalChannel, renderer: ChannelRenderer) -> None:
        self._renderers[channel] = renderer

    # ── 分发 ────────────────────────────────────────────────────

    def dispatch(
        self,
        request: ApprovalRequest,
        channels: list[ApprovalChannel] | None = None,
    ) -> int:
        """分发通知到通道。返回成功发送数。"""
        targets = channels or [ApprovalChannel.WEBCHAT]
        sent = 0
        for ch in targets:
            renderer = self._renderers.get(ch)
            if renderer is None:
                logger.warning("NotificationDispatcher: no renderer for channel %s", ch.value)
                continue

            body = renderer(request)
            notification = ApprovalNotification(
                request_id=request.id,
                channel=ch,
                title=f"Approval required: {request.context.action}",
                body=body,
                actions=["approve", "reject"] if ch != ApprovalChannel.EMAIL else [],
            )
            ok = self._broker.send_notification(notification)
            if ok:
                sent += 1
        return sent

    def dispatch_auto_only(self, request: ApprovalRequest) -> int:
        """自动发送到已注册通道"""
        return self.dispatch(request)

    # ── 通道渲染器 ──────────────────────────────────────────────

    @staticmethod
    def _render_webchat(request: ApprovalRequest) -> str:
        """WebChat 渲染 — 精简卡片"""
        ctx = request.context
        time_left = ""
        if request.expires_at:
            from datetime import datetime, timezone
            remaining = int(request.expires_at.timestamp() - datetime.now(timezone.utc).timestamp())
            time_left = f"{remaining}s left"
        return (
            f"### ⏸ Approval required\n"
            f"Action: `{ctx.action}`\n"
            f"Stage: {ctx.stage}\n"
            f"Agent: {ctx.agent}\n"
            f"Risk: {ctx.risk_level}\n"
            f"Customer: {ctx.customer_name or 'N/A'} ({ctx.company or 'N/A'})\n"
            f"Request ID: `{request.id}`\n"
            f"Timeout: {time_left}\n\n"
        )

    @staticmethod
    def _render_api(request: ApprovalRequest) -> str:
        """API 渲染 — JSON"""
        import json
        return json.dumps({
            "request_id": request.id,
            "pipeline_id": request.pipeline_id,
            "action": request.context.action,
            "stage": request.context.stage,
            "risk_level": request.context.risk_level,
            "mode": request.mode.value,
            "status": request.status.value,
        }, indent=2)

    @staticmethod
    def _render_email(request: ApprovalRequest) -> str:
        """Email 渲染 — 可读文本"""
        ctx = request.context
        return (
            f"Approval required for pipeline {request.pipeline_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Action:  {ctx.action}\n"
            f"Stage:   {ctx.stage}\n"
            f"Agent:   {ctx.agent}\n"
            f"Risk:    {ctx.risk_level}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Request ID: {request.id}\n"
            f"To approve/reject, reply with 'approve {request.id}' or 'reject {request.id}'"
        )
