"""Byou L3 HITL — 审批 Broker。

抽象通信通道: webchat / API / webhook / email
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .types import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalNotification,
    ApprovalRequest,
    ApprovalStatus,
)

logger = logging.getLogger(__name__)

# ── 回调注册 ────────────────────────────────────────────────────

SendCallback = Callable[[ApprovalNotification], Any]
ReceiveCallback = Callable[[ApprovalDecision], Any]


@dataclass
class ChannelRegistration:
    channel: ApprovalChannel
    send: SendCallback | None = None
    receive: ReceiveCallback | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalBroker:
    """审批通道 Broker — 管理多通道 发送/接收

    用法:
        broker = ApprovalBroker()
        broker.register(ApprovalChannel.WEBCHAT, send=send_to_webchat)
        broker.send_notification(notification)  # → 抽象发送
    """

    def __init__(self):
        self._channels: dict[ApprovalChannel, ChannelRegistration] = {}
        self._receive_hook: ReceiveCallback | None = None

    def register(
        self,
        channel: ApprovalChannel,
        send: SendCallback | None = None,
        receive: ReceiveCallback | None = None,
        **metadata,
    ) -> None:
        self._channels[channel] = ChannelRegistration(
            channel=channel, send=send, receive=receive, metadata=metadata,
        )
        logger.info("ApprovalBroker: registered channel %s", channel.value)

    def unregister(self, channel: ApprovalChannel) -> None:
        self._channels.pop(channel, None)

    def set_receive_hook(self, hook: ReceiveCallback) -> None:
        """设置全局接收钩子 (跨所有通道)"""
        self._receive_hook = hook

    # ── 发送 ────────────────────────────────────────────────────

    def send_notification(
        self,
        notification: ApprovalNotification,
    ) -> bool:
        """发送审批通知到指定通道

        Returns:
            True 发送成功, False 通道未注册或无 send callback
        """
        reg = self._channels.get(notification.channel)
        if reg is None:
            logger.warning("ApprovalBroker: channel %s not registered", notification.channel.value)
            return False
        if reg.send is None:
            logger.warning("ApprovalBroker: channel %s has no send callback", notification.channel.value)
            return False

        try:
            reg.send(notification)
            logger.debug("ApprovalBroker: sent notification %s via %s", notification.id, notification.channel.value)
            return True
        except Exception as exc:
            logger.exception("ApprovalBroker: send failed for %s: %s", notification.id, exc)
            return False

    def broadcast(
        self,
        notification: ApprovalNotification,
        channels: list[ApprovalChannel] | None = None,
    ) -> int:
        """向多个通道广播通知"""
        targets = channels or list(self._channels.keys())
        sent = 0
        for ch in targets:
            n = ApprovalNotification(
                request_id=notification.request_id,
                channel=ch,
                title=notification.title,
                body=notification.body,
                recipient=notification.recipient,
                actions=notification.actions,
            )
            if self.send_notification(n):
                sent += 1
        return sent

    # ── 接收 ────────────────────────────────────────────────────

    def receive_decision(
        self,
        request_id: str,
        approved: bool,
        reason: str = "",
        modifications: dict[str, Any] | None = None,
        decided_by: str = "",
        channel: ApprovalChannel = ApprovalChannel.API,
    ) -> ApprovalDecision:
        """接收并路由决策"""
        decision = ApprovalDecision(
            approved=approved,
            reason=reason,
            modifications=modifications or {},
            decided_by=decided_by or f"broker:{channel.value}",
        )
        if self._receive_hook:
            try:
                self._receive_hook(decision)
            except Exception as exc:
                logger.exception("ApprovalBroker: receive_hook error: %s", exc)
        return decision

    # ── 内置发送器: 日志 ────────────────────────────────────────

    @staticmethod
    def log_sender(notification: ApprovalNotification) -> None:
        """内置 log sender — 将通知内容落到日志"""
        logger.info(
            "[APPROVAL NOTIFICATION] id=%s req=%s channel=%s title=%s body=%s",
            notification.id, notification.request_id,
            notification.channel.value, notification.title, notification.body,
        )
