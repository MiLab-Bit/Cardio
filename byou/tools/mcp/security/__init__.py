"""MCP Security Governance — 统一门面。

将各个安全模块组合成一个完整的门面 (Gatekeeper)，
供 Tool Bus 在注册和执行两个阶段引用。

Usage:
    from byou.tools.mcp.security import Gatekeeper

    gk = Gatekeeper()
    await gk.bootstrap_defaults()  # 加载默认 risk profiles

    # 注册前
    audit = await gk.audit_server(profile)
    if audit.is_approved:
        gk.register_server_profile(profile)

    # 执行前
    decision = gk.decide(tool_name=..., capability=..., caller=...)
    if not decision.allowed:
        return error
    if decision.requires_approval:
        result = await gk.request_approval(decision)
"""

from __future__ import annotations

import logging

from byou.tools.mcp.types import MCPToolDescriptor

from .audit import ServerAuditor
from .approvals import ApprovalEngine
from .injection_guard import InjectionGuard
from .policy import SecurityPolicyEngine
from .registry_guard import RegistryGuard
from .scanner import SecurityScanner
from .trust import TrustManager
from .reports import AuditReporter
from .types import (
    ApprovalRequirement,
    AuditStatus,
    CapabilityRiskProfile,
    InjectionCheckResult,
    McpSecurityFinding,
    McpServerAudit,
    McpServerProfile,
    RiskLevel,
    ServerTrustRecord,
    ToolExecutionDecision,
    ToolViolationEvent,
    TrustLevel,
    ViolationCategory,
)

logger = logging.getLogger(__name__)


class Gatekeeper:
    """MCP 安全治理统一门面。

    组合所有安全模块为一个简单的统一接口:
      - audit_server() → 接入前审计
      - register_server_profile() → 注册 server 安全档案
      - decide() → 执行前安全决策
      - request_approval() → 高风险操作审批
      - mark_untrusted() → 标记工具输出为不可信
      - scan_config() → 配置扫描
      - scan_source() → 源代码扫描
    """

    def __init__(self):
        self.auditor = ServerAuditor()
        self.approval_engine = ApprovalEngine()
        self.injection_guard = InjectionGuard()
        self.policy_engine = SecurityPolicyEngine()
        self.registry_guard = RegistryGuard()
        self.scanner = SecurityScanner()
        self.trust_manager = TrustManager()
        self.reporter = AuditReporter()

        self._server_profiles: dict[str, McpServerProfile] = {}

    # ── Bootstrap ─────────────────────────────────

    async def bootstrap_defaults(self) -> None:
        """加载默认配置: risk profiles + agent allowlists。

        应在系统启动时调用一次。
        """
        # 注册默认 risk profiles
        for cap, profile in CapabilityRiskProfile.default_risk_map().items():
            self.policy_engine.register_risk_profile(profile)

        # 默认 Agent 权限
        self.policy_engine.set_agent_allowlist("researcher", {
            "company_lookup", "equity_analysis", "risk_assessment",
            "web_search", "people_search", "vector_search", "data_enrich",
            "browser_automate", "crm_read",
        })
        self.policy_engine.set_agent_allowlist("extractor", {
            "document_ocr",
        })
        self.policy_engine.set_agent_allowlist("strategist", {
            "vector_search", "data_enrich",
        })
        self.policy_engine.set_agent_allowlist("synthesizer", {
            "vector_search",
        })
        self.policy_engine.set_agent_allowlist("critic", set())  # Critic 不调外部工具

        # 禁止高危 capability (生产默认)
        self.policy_engine.deny_capability("email_send")

    # ── Server Onboarding ─────────────────────────

    async def audit_server(self, profile: McpServerProfile) -> McpServerAudit:
        """对新 server 执行完整安全审计。

        Returns:
            McpServerAudit: 包含决策、findings、capability 风险
        """
        audit = await self.auditor.audit(profile)
        return audit

    def register_server_profile(self, profile: McpServerProfile) -> None:
        """注册已审计的 server profile。"""
        self._server_profiles[profile.server_name] = profile

        # 同步至 trust manager
        self.trust_manager.apply_audit_result(
            server_name=profile.server_name,
            trust_score=80,  # 初始信任分
            audit_date=profile.audit_date,
        )

    # ── Tool Registration Guard ───────────────────

    def check_tool_registration(self, tool: MCPToolDescriptor) -> tuple[bool, str]:
        """注册工具前的安全检查。

        Returns:
            (是否可注册, 原因)
        """
        server_profile = self._server_profiles.get(tool.server_name)
        return self.registry_guard.check(tool, server_profile)

    # ── Execution Decision ────────────────────────

    def decide(
        self,
        *,
        tool_name: str,
        capability: str,
        caller: str,
        trace_id: str = "",
        server_name: str = "",
        is_untrusted_context: bool = False,
        tool_output: str = "",
    ) -> ToolExecutionDecision:
        """工具执行前的安全决策。

        完整的安全检查链:
        1. Policy allowlist/denylist
        2. Risk profile
        3. Server trust
        4. Untrusted context gate
        5. Injection guard (检查工具输出)

        Args:
            tool_name: 工具名
            capability: 能力标签
            caller: 调用方 (agent name)
            trace_id: 追踪 ID
            server_name: server 名
            is_untrusted_context: 是否在不可信上下文
            tool_output: 如已有, 检查工具输出是否含注入

        Returns:
            ToolExecutionDecision
        """
        # 注入检测
        injection_result = None
        if tool_output:
            injection_result = self.injection_guard.check(tool_output)

        return self.policy_engine.decide(
            tool_name=tool_name,
            capability=capability,
            caller=caller,
            trace_id=trace_id,
            server_name=server_name,
            is_untrusted_context=is_untrusted_context,
            injection_result=injection_result,
        )

    async def request_approval(self, decision: ToolExecutionDecision):
        """高风险工具审批。"""
        return await self.approval_engine.request_approval(decision)

    # ── Untrusted Output ──────────────────────────

    def mark_untrusted(self, content: str, *, source: str = ""):
        """标记工具输出为不可信内容。

        所有来自外部工具的文本输出都应该经过此标记。
        """
        return self.injection_guard.mark_untrusted(content, source=source)

    def check_injection(self, content: str, *, content_type: str = "tool_output") -> InjectionCheckResult:
        """单独执行注入检测 (用于 Agent 消费工具输出前)。"""
        return self.injection_guard.check(content, content_type=content_type)

    # ── Scanning ──────────────────────────────────

    def scan_config(self, server_name: str, config: dict) -> list[McpSecurityFinding]:
        """扫描配置文件。"""
        return self.scanner.scan_config(server_name, config)

    def scan_source(self, server_name: str, source_dir: str) -> list[McpSecurityFinding]:
        """扫描源代码。"""
        return self.scanner.scan_source(server_name, source_dir)

    # ── Trust ─────────────────────────────────────

    def record_violation(self, server_name: str, violation: ToolViolationEvent) -> ServerTrustRecord:
        """记录安全违规并扣 trust 分。"""
        return self.trust_manager.record_violation(server_name, violation)

    def record_tool_success(self, server_name: str) -> None:
        """记录工具调用成功, 缓慢恢复 trust。"""
        self.trust_manager.record_success(server_name)

    def record_tool_error(self, server_name: str) -> None:
        """记录工具调用错误。"""
        self.trust_manager.record_error(server_name)

    # ── Reports ───────────────────────────────────

    def audit_report(self, audit: McpServerAudit, *, format: str = "text") -> str:
        """生成审计报告。"""
        if format == "json":
            return self.reporter.json_report(audit)
        return self.reporter.text_report(audit)

    def violation_report(self) -> str:
        """生成违规事件报告。"""
        return self.reporter.violation_report(self.policy_engine.get_violations())


__all__ = [
    "Gatekeeper",
    "ServerAuditor",
    "ApprovalEngine",
    "InjectionGuard",
    "SecurityPolicyEngine",
    "RegistryGuard",
    "SecurityScanner",
    "TrustManager",
    "AuditReporter",
    # Types
    "RiskLevel",
    "TrustLevel",
    "ViolationCategory",
    "AuditStatus",
    "ApprovalRequirement",
    "CapabilityRiskProfile",
    "McpServerAudit",
    "McpServerProfile",
    "McpSecurityFinding",
    "ToolExecutionDecision",
    "ToolViolationEvent",
    "ServerTrustRecord",
    "InjectionCheckResult",
]
