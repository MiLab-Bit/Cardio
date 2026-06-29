"""MCP Security — Registry Guard。

在工具注册到 Tool Bus 时执行安全检查:
1. Server 是否已通过审计?
2. Capability risk 是否可接受?
3. 参数 schema 是否有安全隐患?
4. Environment 限制是否合理?
"""

from __future__ import annotations

import logging
import re

from byou.tools.mcp.types import MCPToolDescriptor, ToolCapability

from .types import (
    AuditStatus,
    CapabilityRiskProfile,
    McpServerProfile,
    RiskLevel,
    TrustLevel,
)

logger = logging.getLogger(__name__)


class RegistryGuard:
    """工具注册安全检查。

    在 ToolRegistry.register() 之前调用此 guard,
    确保只有通过安全检查的工具才能注册。

    Usage:
        guard = RegistryGuard()
        ok, reason = guard.check(tool, server_profile)
        if ok:
            registry.register(tool)
    """

    def __init__(
        self,
        *,
        risk_profiles: dict[str, CapabilityRiskProfile] | None = None,
        server_profiles: dict[str, McpServerProfile] | None = None,
    ):
        self._risk_profiles = risk_profiles or CapabilityRiskProfile.default_risk_map()
        self._server_profiles = server_profiles or {}

    # ── Main check ────────────────────────────────

    def check(
        self,
        tool: MCPToolDescriptor,
        server_profile: McpServerProfile | None = None,
    ) -> tuple[bool, str]:
        """检查工具是否可以注册。

        Returns:
            (是否允许注册, 原因)
        """
        # 1. Server 审计状态
        if server_profile:
            ok, reason = self._check_server_audit(server_profile)
            if not ok:
                return False, reason

        # 2. Capability 风险检查
        for cap in tool.capabilities:
            ok, reason = self._check_capability(cap, server_profile)
            if not ok:
                return False, reason

        # 3. 参数 schema 安全检查
        ok, reason = self._check_parameters(tool)
        if not ok:
            return False, reason

        # 4. Environment 检查
        ok, reason = self._check_environments(tool, server_profile)
        if not ok:
            return False, reason

        # 5. 命名安全
        ok, reason = self._check_name(tool)
        if not ok:
            return False, reason

        return True, "All checks passed"

    # ── Individual checks ─────────────────────────

    def _check_server_audit(self, profile: McpServerProfile) -> tuple[bool, str]:
        """Server 是否已通过审计?"""
        if profile.audit_status == AuditStatus.FAILED:
            return False, f"Server '{profile.server_name}' audit FAILED"

        if profile.audit_status == AuditStatus.PENDING:
            return False, f"Server '{profile.server_name}' not yet audited"

        if profile.trust_level in (TrustLevel.QUARANTINED, TrustLevel.BLACKLISTED):
            return False, f"Server '{profile.server_name}' is {profile.trust_level.value}"

        return True, "OK"

    def _check_capability(
        self,
        capability: ToolCapability,
        server_profile: McpServerProfile | None,
    ) -> tuple[bool, str]:
        """检查单个 capability 的风险。"""
        cap_str = capability.value if isinstance(capability, ToolCapability) else str(capability)

        # Server 白名单/黑名单
        if server_profile:
            if server_profile.denied_capabilities and cap_str in server_profile.denied_capabilities:
                return False, f"Capability '{cap_str}' is denied for server '{server_profile.server_name}'"
            if server_profile.allowed_capabilities and cap_str not in server_profile.allowed_capabilities:
                return False, f"Capability '{cap_str}' not in server '{server_profile.server_name}' allowlist"

        # Risk profile
        risk = self._risk_profiles.get(cap_str)
        if risk and risk.risk_level == RiskLevel.CRITICAL:
            if not risk.default_approval:
                return False, f"Capability '{cap_str}' is CRITICAL - requires explicit approval config"

        return True, "OK"

    def _check_parameters(self, tool: MCPToolDescriptor) -> tuple[bool, str]:
        """检查工具参数是否有安全风险。"""
        for param in tool.parameters:
            # 参数名包含可疑关键字
            name_lower = param.name.lower()
            dangerous_names = {"password", "token", "secret", "apikey", "api_key",
                               "auth", "passwd", "credential", "private_key"}
            if name_lower in dangerous_names:
                logger.warning("Tool '%s' parameter '%s' looks like a credential parameter",
                              tool.name, param.name)

            # 默认值含可疑模式
            if param.default and isinstance(param.default, str):
                if re.match(r'^[A-Za-z0-9+/]{20,}=*$', param.default):
                    logger.warning("Tool '%s' parameter '%s' default looks like base64-encoded value",
                                  tool.name, param.name)

        return True, "OK"

    def _check_environments(
        self,
        tool: MCPToolDescriptor,
        server_profile: McpServerProfile | None,
    ) -> tuple[bool, str]:
        """检查环境配置是否合理。"""
        if "production" not in tool.environments:
            # 允许 (某些工具只在 dev/staging)
            pass

        envs = set(tool.environments)
        dangerous_envs = envs & {"*", "all", "any"}
        if dangerous_envs:
            return False, f"Tool '{tool.name}' has overly broad environment scope: {dangerous_envs}"

        return True, "OK"

    def _check_name(self, tool: MCPToolDescriptor) -> tuple[bool, str]:
        """检查工具名是否包含危险字符。"""
        name = tool.name

        if ".." in name or "/" in name or "\\" in name:
            return False, f"Tool name '{name}' contains path traversal characters"

        if len(name) > 128:
            return False, f"Tool name '{name}' too long (>128 chars)"

        if not re.match(r'^[\w.\-]+$', name):
            return False, f"Tool name '{name}' contains invalid characters (only [a-zA-Z0-9_.-] allowed)"

        return True, "OK"
