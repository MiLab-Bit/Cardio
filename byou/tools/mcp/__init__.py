"""MCP Tool Bus — Byou 工具总线的公共接口。

导出:
- 全部数据模型 (types)
- ToolRegistry — 注册/发现
- MCPClientManager — 连接管理
- ToolInvocationEngine — 调用引擎
- PolicyEngine — 策略引擎
- AuthProvider — 鉴权
- ToolBus — Agent 调用的唯一门面
- map_error — 异常映射
"""

from byou.tools.mcp.types import (
    # 描述符
    MCPToolDescriptor,
    MCPToolParameter,
    ParameterType,
    # 能力标签
    ToolCapability,
    ToolCategory,
    # 调用
    MCPToolCallRequest,
    MCPToolCallResult,
    # 错误
    MCPToolError,
    ErrorCategory,
    # 配置
    MCPServerConfig,
    MCPAuthConfig,
    MCPAuthType,
    MCPServerType,
    # 策略
    MCPInvocationPolicy,
    RetryStrategy,
    CircuitState,
    # 会话
    MCPSessionInfo,
    MCPSessionState,
    # 审计
    AuditEntry,
    AuditEventType,
)

from byou.tools.mcp.registry import ToolRegistry
from byou.tools.mcp.client_manager import MCPClientManager
from byou.tools.mcp.invocation import ToolInvocationEngine
from byou.tools.mcp.policies import PolicyEngine
from byou.tools.mcp.auth import AuthProvider
from byou.tools.mcp.errors import map_error
from byou.tools.mcp.bus import ToolBus

__all__ = [
    # types
    "MCPToolDescriptor", "MCPToolParameter", "ParameterType",
    "ToolCapability", "ToolCategory",
    "MCPToolCallRequest", "MCPToolCallResult",
    "MCPToolError", "ErrorCategory",
    "MCPServerConfig", "MCPAuthConfig", "MCPAuthType", "MCPServerType",
    "MCPInvocationPolicy", "RetryStrategy", "CircuitState",
    "MCPSessionInfo", "MCPSessionState",
    "AuditEntry", "AuditEventType",
    # core
    "ToolRegistry", "MCPClientManager", "ToolInvocationEngine",
    "PolicyEngine", "AuthProvider",
    # facade
    "ToolBus",
    # errors
    "map_error",
]
