"""Byou L3 HITL — 审批策略引擎。

匹配 ApprovalPolicyRule → ApprovalMode
"""

from __future__ import annotations

import fnmatch
import logging

from .types import (
    ApprovalContext,
    ApprovalMode,
    ApprovalPolicyRule,
    ApprovalPolicyStore,
    ApprovalScope,
    EscalationPolicy,
)

logger = logging.getLogger(__name__)

# 内置默认策略表
DEFAULT_RULES: list[ApprovalPolicyRule] = [
    # ── 低风险: 自动通过 ──
    ApprovalPolicyRule(
        name="low_risk_read",
        capability_pattern="COMPANY_LOOKUP",
        approval_mode=ApprovalMode.AUTO,
        min_risk_level="low",
        priority=100,
    ),
    ApprovalPolicyRule(
        name="safe_read",
        action_pattern="read_*",
        approval_mode=ApprovalMode.AUTO,
        min_risk_level="low",
        priority=90,
    ),
    # ── 中风险: 事后审查 ──
    ApprovalPolicyRule(
        name="medium_risk_search",
        capability_pattern="BATCH_SEARCH",
        approval_mode=ApprovalMode.DEFER,
        min_risk_level="medium",
        priority=80,
    ),
    ApprovalPolicyRule(
        name="medium_risk_web",
        action_pattern="web_search_*",
        approval_mode=ApprovalMode.DEFER,
        min_risk_level="medium",
        priority=70,
    ),
    # ── 高风险: 暂停审批 ──
    ApprovalPolicyRule(
        name="high_risk_write",
        capability_pattern="WRITE_CRM",
        approval_mode=ApprovalMode.DEMAND,
        min_risk_level="high",
        timeout_s=600,
        priority=60,
    ),
    ApprovalPolicyRule(
        name="stage_strategy",
        stage_pattern="strategy",
        approval_mode=ApprovalMode.DEMAND,
        min_risk_level="high",
        timeout_s=600,
        scope=ApprovalScope.STAGE,
        priority=50,
    ),
    # ── 致命风险: 必须人工 ──
    ApprovalPolicyRule(
        name="critical_export",
        capability_pattern="MASS_EXPORT",
        approval_mode=ApprovalMode.HUMAN_REQUIRED,
        min_risk_level="critical",
        timeout_s=1800,
        max_approvals=2,
        escalation=EscalationPolicy.AUTO_REJECT,
        priority=40,
    ),
    ApprovalPolicyRule(
        name="critical_delete",
        action_pattern="delete_*",
        approval_mode=ApprovalMode.HUMAN_REQUIRED,
        min_risk_level="critical",
        timeout_s=1800,
        max_approvals=2,
        priority=30,
    ),
    # ── 兜底 ── (去掉全局匹配的兜底规则, 由 match() 的 fallback 逻辑根据 risk_level 动态处理)
    # default_demand 已废弃 — risk-based fallback 在 match() 末尾处理
]


class ApprovalPolicyEngine:
    """审批策略引擎 — 规则匹配 + 默认值"""

    def __init__(self, store: ApprovalPolicyStore | None = None):
        self._store = store or ApprovalPolicyStore(rules=list(DEFAULT_RULES))

    @property
    def rules(self) -> list[ApprovalPolicyRule]:
        return self._store.rules

    def add_rule(self, rule: ApprovalPolicyRule) -> None:
        self._store.rules.append(rule)
        self._store.rules.sort(key=lambda r: r.priority, reverse=True)

    def match(self, context: ApprovalContext) -> ApprovalPolicyRule:
        """匹配最高优先级的规则。

        匹配逻辑: priority 从高到低, 第一个全部 pattern match 的规则命中。
        """
        for rule in self._store.rules:
            if not fnmatch.fnmatch(context.action, rule.action_pattern):
                continue
            if not fnmatch.fnmatch(
                context.capability or "*", rule.capability_pattern
            ):
                continue
            if not fnmatch.fnmatch(context.stage or "*", rule.stage_pattern):
                continue
            if not fnmatch.fnmatch(
                context.tool_name or "*", rule.tool_pattern
            ):
                continue
            # risk_level 比较
            risk_ok = self._risk_meets_minimum(
                getattr(context, "risk_level", "low"), rule.min_risk_level
            )
            if not risk_ok:
                continue
            logger.debug("Approval policy matched: rule=%s action=%s", rule.name, context.action)
            return rule

        # 兜底: 根据 risk_level 选择合理的默认模式
        logger.debug("No policy matched for action=%s, using risk-based default", context.action)
        risk_mode = {"low": ApprovalMode.AUTO, "medium": ApprovalMode.DEFER,
                     "high": ApprovalMode.DEMAND, "critical": ApprovalMode.HUMAN_REQUIRED}
        actual_risk = getattr(context, "risk_level", "medium") or "medium"
        fallback_mode = risk_mode.get(actual_risk, ApprovalMode.DEMAND)
        return ApprovalPolicyRule(
            name="fallback",
            approval_mode=fallback_mode,
            timeout_s=self._store.default_timeout_s,
            action_pattern=context.action,
        )

    @staticmethod
    def _risk_meets_minimum(actual: str, minimum: str) -> bool:
        """判断 actual >= minimum (语义化)"""
        _order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return _order.get(actual, 0) >= _order.get(minimum, 0)
