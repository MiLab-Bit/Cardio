"""Byou Governance — HITL 审批与策略治理子系统。

注入位置:
    from byou.production.governance import ApprovalManager, PipelineHooks

    am = ApprovalManager()
    hooks = PipelineHooks(am.engine)

    # 在 Orchestrator 每个 stage 前:
    result = hooks.before_stage("strategy", pipeline_id, action="generate_bd_strategy")
    if isinstance(result, ApprovalRequest) and result.status == ApprovalStatus.PENDING:
        decision = await hooks.pause_pipeline(result)
        if not decision.approved:
            raise PipelineRejected("Strategy generation rejected")

    # WebChat 收到用户 approve:
    hooks.resume(request_id, ApprovalDecision(approved=True))
"""

from __future__ import annotations

import logging

from .broker import ApprovalBroker
from .engine import ApprovalEngine, APPROVAL_HALT
from .hooks import PipelineHooks
from .notify import NotificationDispatcher
from .policy import ApprovalPolicyEngine, DEFAULT_RULES
from .store import ApprovalStore
from .types import (
    ApprovalChannel,
    ApprovalContext,
    ApprovalDecision,
    ApprovalEvent,
    ApprovalMode,
    ApprovalNotification,
    ApprovalPolicyRule,
    ApprovalPolicyStore,
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    EscalationPolicy,
)

logger = logging.getLogger(__name__)


class ApprovalManager:
    """审批子系统统一门面 — 一行初始化全部组件

    用法:
        am = ApprovalManager(db_path="data/approvals.db")
        await am.start()

        # 注册 webchat 通道
        am.register_webchat(send_callback=send_chat)
    """

    def __init__(
        self,
        db_path: str | None = None,
        policy_store: ApprovalPolicyStore | None = None,
    ):
        self._store = ApprovalStore(db_path=db_path)
        self._policy = ApprovalPolicyEngine(store=policy_store)
        self._broker = ApprovalBroker()
        self._engine = ApprovalEngine(
            store=self._store,
            policy_engine=self._policy,
        )
        self._dispatcher = NotificationDispatcher(broker=self._broker)
        self._hooks = PipelineHooks(engine=self._engine)

    # ── 属性访问 ──

    @property
    def engine(self) -> ApprovalEngine:
        return self._engine

    @property
    def store(self) -> ApprovalStore:
        return self._store

    @property
    def broker(self) -> ApprovalBroker:
        return self._broker

    @property
    def dispatcher(self) -> NotificationDispatcher:
        return self._dispatcher

    @property
    def hooks(self) -> PipelineHooks:
        return self._hooks

    @property
    def policy_engine(self) -> ApprovalPolicyEngine:
        return self._policy

    # ── 便捷方法 ──

    def register_webchat(self, send_callback=None, receive_callback=None) -> None:
        """注册 webchat 通道"""
        self._broker.register(
            ApprovalChannel.WEBCHAT,
            send=send_callback or self._default_webchat_send,
            receive=receive_callback,
        )

    def register_api(self, send_callback=None, receive_callback=None) -> None:
        """注册 API 通道"""
        self._broker.register(
            ApprovalChannel.API,
            send=send_callback or self._broker.log_sender,
            receive=receive_callback,
        )

    def decide(self, request_id: str, approved: bool, reason: str = "", decided_by: str = "") -> ApprovalRequest | None:
        """便捷决策入口"""
        decision = ApprovalDecision(
            approved=approved, reason=reason, decided_by=decided_by,
        )
        self._broker.receive_decision(request_id, approved, reason, decided_by=decided_by)
        return self._engine.decide(request_id, decision)

    async def start(self) -> None:
        """启动后台巡检任务"""
        logger.info("ApprovalManager started")

    async def shutdown(self) -> None:
        """优雅关闭"""
        logger.info("ApprovalManager shutdown")

    @staticmethod
    def _default_webchat_send(notification: ApprovalNotification) -> None:
        """默认 webchat 发送 — 落到日志"""
        logger.info(
            "[APPROVAL] %s | action=%s | channel=WEBCHAT | body=%s",
            notification.request_id, notification.title, notification.body,
        )


__all__ = [
    # Manager
    "ApprovalManager",
    "PipelineHooks",
    "APPROVAL_HALT",
    # Engine & Policy
    "ApprovalEngine",
    "ApprovalPolicyEngine",
    "DEFAULT_RULES",
    # Store & Broker
    "ApprovalStore",
    "ApprovalBroker",
    "NotificationDispatcher",
    # Types
    "ApprovalMode",
    "ApprovalStatus",
    "ApprovalChannel",
    "ApprovalScope",
    "EscalationPolicy",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalContext",
    "ApprovalNotification",
    "ApprovalEvent",
    "ApprovalPolicyRule",
    "ApprovalPolicyStore",
]
