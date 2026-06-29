"""MCP Tool Bus — 调用沙箱。

生产环境安全控制:
- 禁止特定环境使用写操作工具
- 禁止特定 Agent 访问敏感工具
- 参数篡改检测
"""

from __future__ import annotations

import logging

from byou.tools.mcp.types import (
    MCPToolDescriptor,
    MCPToolCallRequest,
    MCPToolError,
    ErrorCategory,
)

logger = logging.getLogger(__name__)

# 默认禁用的能力 (生产环境)
_DISABLED_IN_PRODUCTION = {
    # "crm_write",  # 生产环境禁止 CRM 写入
}

# 默认禁用的工具名
_DISABLED_TOOLS: set[str] = set()

# 危险参数模式
_DANGEROUS_ARG_PATTERNS = [
    ("rm", "rf"),
    ("drop", "table"),
    ("eval",),
    ("exec:",),
]


class ToolSandbox:
    """工具调用沙箱 — 安全护栏。

    在 invocation engine 执行前对请求做安全检查。
    """

    def __init__(self):
        self._disabled_tools = set(_DISABLED_TOOLS)
        self._disabled_caps = set(_DISABLED_IN_PRODUCTION)

    def disable_tool(self, tool_name: str) -> None:
        """沙箱禁用某工具"""
        self._disabled_tools.add(tool_name)

    def enable_tool(self, tool_name: str) -> None:
        self._disabled_tools.discard(tool_name)

    def disable_capability(self, cap: str) -> None:
        """沙箱禁用某类能力"""
        self._disabled_caps.add(cap)

    def check(
        self,
        descriptor: MCPToolDescriptor,
        request: MCPToolCallRequest,
        environment: str = "production",
    ) -> MCPToolError | None:
        """执行安全检查。

        Returns:
            None = 通过, MCPToolError = 拦截
        """
        # 1. 工具黑名单
        if descriptor.name in self._disabled_tools:
            return MCPToolError(
                tool_name=descriptor.name,
                category=ErrorCategory.AUTH,
                message=f"Tool {descriptor.name} is sandboxed",
                retryable=False,
            )

        # 2. 生产环境禁止写操作
        if environment == "production" and not descriptor.is_readonly:
            for cap in descriptor.capabilities:
                if cap.value in self._disabled_caps:
                    return MCPToolError(
                        tool_name=descriptor.name,
                        category=ErrorCategory.AUTH,
                        message=f"Write operations blocked in production: {cap.value}",
                        retryable=False,
                    )

        # 3. 参数安全检查
        for key, val in request.arguments.items():
            if isinstance(val, str):
                for pattern in _DANGEROUS_ARG_PATTERNS:
                    if all(p in val.lower() for p in pattern):
                        return MCPToolError(
                            tool_name=descriptor.name,
                            category=ErrorCategory.VALIDATION,
                            message=f"Dangerous argument pattern detected in '{key}': {val}",
                            retryable=False,
                        )

        return None
