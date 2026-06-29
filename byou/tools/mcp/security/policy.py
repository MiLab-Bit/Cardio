"""MCP Security — 安全策略决策引擎。

在现有 PolicyEngine (mcp/policies.py: 超时/重试/熔断) 基础上
增加安全维度的策略:
1. Capability allowlist / denylist (per-agent / per-environment)
2. Pre-execution 安全决策 (ToolExecutionDecision)
3. Untrusted context gate
4. 高风险操作审批 gate
"""

from __future__ import annotations

import logging
from datetime import datetime

from byou.tools.mcp.types import ToolCapability

from .types import (
    ApprovalRequirement,
    CapabilityRiskProfile,
    InjectionCheckResult,
    RiskLevel,
    ServerTrustRecord,
    ToolExecutionDecision,
    ToolViolationEvent,
    TrustLevel,
    ViolationCategory,
)

logger = logging.getLogger(__name__)


class SecurityPolicyEngine:
    """安全策略引擎 — 在工具执行前做安全决策。

    与 existing PolicyEngine (mcp/policies.py) 的关系:
      PolicyEngine: 超时/重试/熔断/限流 (运行时韧性)
      SecurityPolicyEngine: 权限/风险/审批/注入 (安全治理)

    调用顺序:
      1. SecurityPolicyEngine.decide() → 安全决策
      2. 如果需要审批 → 等待/拒绝
      3. PolicyEngine.execute_with_policy() → 运行时保护
    """

    def __init__(self):
        # Agent capability allowlist: agent_name → {capability,...}
        self._agent_allowlist: dict[str, set[str]] = {}

        # Capability denylist (global)
        self._global_denylist: set[str] = set()

        # Environment policy
        # env → allowed_capabilities | denied_capabilities
        self._env_policy: dict[str, dict[str, set[str]]] = {}

        # Risk profile cache: capability → CapabilityRiskProfile
        self._risk_profiles: dict[str, CapabilityRiskProfile] = {}

        # Trust records: server_name → ServerTrustRecord
        self._trust_records: dict[str, ServerTrustRecord] = {}

        # Violation history
        self._violations: list[ToolViolationEvent] = []

    # ── Agent Allowlist ───────────────────────────

    def set_agent_allowlist(self, agent_name: str, capabilities: set[str]) -> None:
        """设置 Agent 的能力白名单。

        只有白名单中的 capability 才能被该 Agent 调用。
        未设置 → 默认拒绝所有 (零信任策略)。
        """
        self._agent_allowlist[agent_name] = capabilities

    def get_agent_capabilities(self, agent_name: str) -> set[str]:
        """获取 Agent 的 allowlisted capabilities。"""
        return self._agent_allowlist.get(agent_name, set())

    def agent_has_capability(self, agent_name: str, capability: str) -> bool:
        """检查 Agent 是否有某个 capability。"""
        caps = self._agent_allowlist.get(agent_name)
        if caps is None:
            return False
        return capability in caps

    # ── Global Denylist ───────────────────────────

    def deny_capability(self, capability: str) -> None:
        """全局禁止某个 capability。"""
        self._global_denylist.add(capability)

    def allow_capability(self, capability: str) -> None:
        """从全局黑名单中移除。"""
        self._global_denylist.discard(capability)

    def is_denied(self, capability: str) -> bool:
        """capability 是否全局禁止。"""
        return capability in self._global_denylist

    # ── Risk Profiles ─────────────────────────────

    def register_risk_profile(self, profile: CapabilityRiskProfile) -> None:
        """注册一个 capability 的风险档案。"""
        self._risk_profiles[profile.capability] = profile

    def get_risk_profile(self, capability: str) -> CapabilityRiskProfile | None:
        return self._risk_profiles.get(capability)

    # ── Trust Records ─────────────────────────────

    def register_trust_record(self, record: ServerTrustRecord) -> None:
        self._trust_records[record.server_name] = record

    def get_trust(self, server_name: str) -> TrustLevel:
        """获取 server 当前信任级别。"""
        r = self._trust_records.get(server_name)
        return r.trust_level if r else TrustLevel.UNTRUSTED

    # ── Core Decision ─────────────────────────────

    def decide(
        self,
        *,
        tool_name: str,
        capability: str,
        caller: str,
        trace_id: str,
        server_name: str = "",
        is_untrusted_context: bool = False,
        injection_result: InjectionCheckResult | None = None,
    ) -> ToolExecutionDecision:
        """执行前安全决策。

        检查顺序:
        1. Global denylist → 直接拒绝
        2. Agent allowlist → 不在白名单 → 拒绝
        3. Risk profile → 确定风险等级 + 审批需求
        4. Server trust → 检查信任级别
        5. Untrusted context gate → 高+不可信 → 拒绝
        6. Injection check → 发现注入 → 拒绝

        返回 ToolExecutionDecision, 包含:
          - allowed: 是否允许
          - requires_approval: 是否需要审批
          - risk_level / trust_level: 审计信息
        """
        decision = ToolExecutionDecision(
            tool_name=tool_name,
            capability=capability,
            caller=caller,
            trace_id=trace_id,
            allowed=False,
            is_untrusted_context=is_untrusted_context,
        )

        # ── Step 1: Global denylist ──
        if self.is_denied(capability):
            decision.allowed = False
            decision.reason = f"Capability '{capability}' is globally denied"
            decision.checks_failed.append("global_denylist")
            logger.warning("SecurityPolicy DENY: %s (global denylist)", capability)
            self._record_violation(tool_name, capability, caller, trace_id, server_name,
                                   ViolationCategory.CAPABILITY_ESCALATION, decision.reason)
            return decision

        decision.checks_passed.append("global_denylist")

        # ── Step 2: Agent allowlist ──
        if not self.agent_has_capability(caller, capability):
            decision.allowed = False
            decision.reason = f"Agent '{caller}' is not authorized for capability '{capability}'"
            decision.checks_failed.append("agent_allowlist")
            logger.warning("SecurityPolicy DENY: agent=%s lacks cap=%s", caller, capability)
            self._record_violation(tool_name, capability, caller, trace_id, server_name,
                                   ViolationCategory.OVER_PRIVILEGED, decision.reason)
            return decision

        decision.checks_passed.append("agent_allowlist")

        # ── Step 3: Risk profile ──
        risk = self.get_risk_profile(capability)
        if risk:
            decision.risk_level = risk.risk_level
            decision.requires_approval = risk.default_approval in (
                ApprovalRequirement.HUMAN_REQUIRED, ApprovalRequirement.AUTO_APPROVE
            )
            decision.approval_status = risk.default_approval
        else:
            decision.risk_level = RiskLevel.MEDIUM  # 默认

        # ── Step 4: Server trust ──
        trust = self.get_trust(server_name) if server_name else TrustLevel.UNTRUSTED
        decision.trust_level = trust

        if trust == TrustLevel.BLACKLISTED:
            decision.allowed = False
            decision.reason = f"Server '{server_name}' is blacklisted"
            decision.checks_failed.append("server_trust")
            self._record_violation(tool_name, capability, caller, trace_id, server_name,
                                   ViolationCategory.UNTRUSTED_SERVER, decision.reason)
            return decision

        if trust == TrustLevel.QUARANTINED:
            # 隔离: 高风险 cap 不允许
            if decision.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                decision.allowed = False
                decision.reason = f"Server '{server_name}' is quarantined, HIGH risk capability denied"
                decision.checks_failed.append("server_trust")
                return decision

        if trust == TrustLevel.UNTRUSTED and decision.risk_level >= RiskLevel.HIGH:
            # 未审计 server + 高风险 capability → 拒绝
            decision.allowed = False
            decision.reason = f"Server '{server_name}' is untrusted, HIGH risk capability denied"
            decision.checks_failed.append("server_trust")
            self._record_violation(tool_name, capability, caller, trace_id, server_name,
                                   ViolationCategory.UNTRUSTED_SERVER, decision.reason)
            return decision

        decision.checks_passed.append("server_trust")

        # ── Step 5: Untrusted context gate ──
        if is_untrusted_context and decision.risk_level >= RiskLevel.HIGH:
            risk_profile = self.get_risk_profile(capability)
            if risk_profile and not risk_profile.allow_in_untrusted_context:
                decision.allowed = False
                decision.reason = f"Capability '{capability}' (HIGH risk) blocked in untrusted context"
                decision.checks_failed.append("untrusted_context_gate")
                logger.warning("SecurityPolicy DENY: %s in untrusted context", capability)
                return decision

        decision.checks_passed.append("untrusted_context_gate")

        # ── Step 6: Injection check ──
        if injection_result and not injection_result.passed:
            decision.allowed = False
            decision.reason = f"Injection detected: {injection_result.patterns_matched}"
            decision.checks_failed.append("injection_guard")
            self._record_violation(tool_name, capability, caller, trace_id, server_name,
                                   ViolationCategory.PROMPT_INJECTION, decision.reason)
            return decision

        decision.checks_passed.append("injection_guard")

        # ── All checks passed ──
        decision.allowed = True
        decision.reason = "All security checks passed"

        logger.debug(
            "SecurityPolicy ALLOW: tool=%s cap=%s agent=%s risk=%s trust=%s",
            tool_name, capability, caller, decision.risk_level, decision.trust_level,
        )
        return decision

    # ── Record violation ──────────────────────────

    def _record_violation(
        self,
        tool_name: str,
        capability: str,
        caller: str,
        trace_id: str,
        server_name: str,
        violation_type: ViolationCategory,
        reason: str,
    ) -> None:
        event = ToolViolationEvent(
            event_id=f"viol-{datetime.now().timestamp():.0f}",
            violation_type=violation_type,
            tool_name=tool_name,
            capability=capability,
            caller=caller,
            trace_id=trace_id,
            server_name=server_name,
            description=reason,
            action_taken="blocked",
            policy_rule=violation_type.value,
        )
        self._violations.append(event)

    # ── Queries ───────────────────────────────────

    def get_violations(self, limit: int = 50) -> list[ToolViolationEvent]:
        """获取最近的违规事件。"""
        return self._violations[-limit:]

    def get_violation_count(self) -> int:
        return len(self._violations)

    # ── Environment policy ────────────────────────

    def set_env_policy(
        self,
        env: str,
        *,
        allow: set[str] | None = None,
        deny: set[str] | None = None,
    ) -> None:
        """为特定环境设置 capability 策略。"""
        if env not in self._env_policy:
            self._env_policy[env] = {"allow": set(), "deny": set()}
        if allow:
            self._env_policy[env]["allow"] |= allow
        if deny:
            self._env_policy[env]["deny"] |= deny
