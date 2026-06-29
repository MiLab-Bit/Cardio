"""MCP Security — 高风险操作审批引擎。

当 ToolExecutionDecision 标记 requires_approval=True 时，
调用此模块进行审批处理。

模式:
  - NONE: 直接执行
  - LOG_ONLY: 执行 + 记录
  - AUTO_APPROVE: 自动批准 (预定义条件)
  - HUMAN_REQUIRED: 需要人工审批 (当前为占位, 后续 L3 实现)
  - BLOCK: 直接拒绝
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from .types import (
    ApprovalRequest,
    ApprovalRequirement,
    ApprovalResult,
    RiskLevel,
    ToolExecutionDecision,
)

logger = logging.getLogger(__name__)


class ApprovalEngine:
    """高风险工具调用审批引擎。

    当前版本:
      - LOG_ONLY / AUTO_APPROVE: 自动处理
      - HUMAN_REQUIRED: 记录审批请求 (L3: 对接 Human-in-the-loop)

    不阻塞工具调用流程 — 而是与 policy engine 解耦。
    """

    def __init__(self, *, default_timeout_seconds: int = 300):
        self._pending: dict[str, ApprovalRequest] = {}
        self._results: dict[str, ApprovalResult] = {}
        self.default_timeout = default_timeout_seconds

    # ── 审批决策 ───────────────────────────────────

    async def request_approval(self, decision: ToolExecutionDecision) -> ApprovalResult:
        """请求一次工具调用审批。

        根据决策中的 approval_status 选择处理方式。
        """
        approval_status = decision.approval_status or ApprovalRequirement.NONE

        if approval_status == ApprovalRequirement.NONE:
            # 无需审批 → 直接放行
            return ApprovalResult(
                request_id="",
                approved=True,
                approved_by="policy:none",
                reason="No approval required",
            )

        if approval_status == ApprovalRequirement.LOG_ONLY:
            # 仅记录 → 放行 + 写审计日志
            logger.info("High-risk tool call LOG_ONLY: tool=%s agent=%s risk=%s",
                        decision.tool_name, decision.caller, decision.risk_level)
            return ApprovalResult(
                request_id="",
                approved=True,
                approved_by="policy:log_only",
                reason="High risk call logged",
            )

        if approval_status == ApprovalRequirement.BLOCK:
            # 直接拒绝
            logger.warning("High-risk tool call BLOCKED: tool=%s agent=%s",
                           decision.tool_name, decision.caller)
            return ApprovalResult(
                request_id="",
                approved=False,
                approved_by="policy:block",
                reason=f"Tool {decision.tool_name} is blocked by policy",
            )

        if approval_status == ApprovalRequirement.AUTO_APPROVE:
            # 自动批准 (低风险或有预授权)
            auto_result = self._auto_approve(decision)
            if auto_result:
                return auto_result
            # fallback: 降级为 log only
            logger.info("Auto-approve rule not matched for tool=%s, falling back to LOG_ONLY",
                        decision.tool_name)
            return ApprovalResult(
                request_id="",
                approved=True,
                approved_by="policy:auto_fallback",
                reason="No auto-approve rule matched, allowed with logging",
            )

        if approval_status == ApprovalRequirement.HUMAN_REQUIRED:
            # 需要人工审批 — 当前为占位实现
            return await self._human_approval(decision)

        # 未知状态 → 保守: 拒绝
        return ApprovalResult(
            request_id="",
            approved=False,
            approved_by="policy:unknown",
            reason=f"Unknown approval status: {approval_status}",
        )

    # ── Auto-approve ───────────────────────────────

    def _auto_approve(self, decision: ToolExecutionDecision) -> ApprovalResult | None:
        """自动批准规则。

        满足以下条件自动批准:
        - risk_level <= MEDIUM
        - trust_level >= PARTIAL
        - 不在 untrusted context
        """
        if decision.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return ApprovalResult(
                request_id="",
                approved=True,
                approved_by="policy:auto_approve",
                reason=f"Low/Medium risk cap: {decision.capability}",
                restrictions=[],
            )

        # HIGH + trusted → 自动批准但加限制
        if decision.risk_level == RiskLevel.HIGH and decision.trust_level.value in ("full", "partial"):
            return ApprovalResult(
                request_id="",
                approved=True,
                approved_by="policy:auto_approve",
                reason=f"High risk but trusted server: {decision.capability}",
                restrictions=["timeout_halved", "output_redacted"],
            )

        return None

    # ── Human approval (占位) ──────────────────────

    async def _human_approval(self, decision: ToolExecutionDecision) -> ApprovalResult:
        """人工审批 — 占位实现。

        L3 将对接实际的 Human-in-the-loop 流程:
        - 通知审批人 (企微/邮件)
        - 等待审批人决策
        - 超时自动拒绝

        当前: 创建审批请求 + 超时自动拒绝。
        """
        request_id = f"apr-{uuid.uuid4().hex[:12]}"

        approval_req = ApprovalRequest(
            request_id=request_id,
            tool_name=decision.tool_name,
            capability=decision.capability,
            caller=decision.caller,
            risk_level=decision.risk_level,
            reason=f"Human approval required for HIGH risk tool: {decision.tool_name}",
            ttl_seconds=self.default_timeout,
            auto_reject=True,  # 超时自动拒绝
        )

        self._pending[request_id] = approval_req

        logger.warning(
            "HUMAN_APPROVAL_REQUIRED: id=%s tool=%s agent=%s risk=%s",
            request_id, decision.tool_name, decision.caller, decision.risk_level,
        )

        # 等待 (在实际 L3 中这里等待审批结果)
        # 当前: 立即自动拒绝 (安全优先)
        await asyncio.sleep(0)

        result = ApprovalResult(
            request_id=request_id,
            approved=False,
            approved_by="system:auto_deny",
            reason="Human approval not yet implemented; auto-denying as safety default",
        )

        self._results[request_id] = result
        return result

    # ── Queries ───────────────────────────────────

    def pending_count(self) -> int:
        return len(self._pending)

    def get_pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    def get_result(self, request_id: str) -> ApprovalResult | None:
        return self._results.get(request_id)
