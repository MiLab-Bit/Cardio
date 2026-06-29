"""MCP Tool Bus — ToolBus 门面。

Agent 调用外部工具的唯一入口。
Agent 不需要了解 Registry / Policy / Client 的内部细节，
只通过 ToolBus 的两个方法来调用工具:
  - call(capability, arguments)   → 按能力声明调用
  - call_by_name(tool_name, args) → 按具体工具名调用 (仅调试用)
"""

from __future__ import annotations

import logging

from byou.tools.mcp.types import (
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolDescriptor,
    MCPToolError,
    MCPInvocationPolicy,
    ToolCapability,
)

from byou.tools.mcp.registry import ToolRegistry
from byou.tools.mcp.client_manager import MCPClientManager
from byou.tools.mcp.invocation import ToolInvocationEngine
from byou.tools.mcp.policies import PolicyEngine
from byou.tools.mcp.auth import AuthProvider

logger = logging.getLogger(__name__)


class ToolBus:
    """Agent 调用外部工具的唯一门面。

    设计原则:
    1. Agent 不认工具名，只认 capability
    2. ToolBus 内部处理 registry → tool name → server 的映射
    3. 所有调用走 invocation engine 进行策略保护
    4. 一个系统只有一个 ToolBus 实例，由 Orchestrator 持有

    Usage:
        # 初始化
        bus = ToolBus()
        bus.registry.grant_agent("researcher", {ToolCapability.COMPANY_LOOKUP})

        # Agent 调用
        result = await bus.call(
            capability=ToolCapability.COMPANY_LOOKUP,
            arguments={"company_name": "阿里巴巴"},
            caller="researcher",
        )
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        client_manager: MCPClientManager | None = None,
        policy_engine: PolicyEngine | None = None,
        auth_provider: AuthProvider | None = None,
    ):
        self.registry = registry or ToolRegistry()
        self._clients = client_manager or MCPClientManager()
        self._auth = auth_provider or AuthProvider()

        self._policies = policy_engine or PolicyEngine()
        self._invocation = ToolInvocationEngine(
            client_manager=self._clients,
            policy_engine=self._policies,
            auth_provider=self._auth,
        )

    # ── 能力声明调用 (推荐) ──────────────────

    async def call(
        self,
        capability: ToolCapability,
        arguments: dict,
        *,
        caller: str = "",
        environment: str = "production",
        timeout_ms: int | None = None,
    ) -> MCPToolCallResult:
        """按能力声明调用工具。

        Agent 说 "我需要 COMPANY_LOOKUP"，
        ToolBus 负责找到最合适的工具并执行。
        不需要知道具体工具名 (tianyancha vs qichacha)。

        Args:
            capability: 工具能力标签
            arguments: 调用参数
            caller: 调用方 (Agent name)
            environment: 环境过滤
            timeout_ms: 覆盖默认超时

        Returns:
            MCPToolCallResult

        Raises:
            MCPToolError: 调用失败 (带有 category + retryable)
        """
        # 1. 找工具
        descriptor = self.registry.get_best_tool(capability, environment)
        if descriptor is None:
            raise MCPToolError(
                tool_name=f"capability:{capability}",
                category="not_found",
                message=f"No tool registered for capability: {capability}",
                retryable=False,
            )

        # 2. 权限检查
        if not self.registry.agent_can_use(caller, capability):
            raise MCPToolError(
                tool_name=descriptor.name,
                category="auth",
                message=f"Agent '{caller}' not authorized for capability: {capability}",
                retryable=False,
            )

        # 3. 构建请求
        request = MCPToolCallRequest(
            tool_name=descriptor.name,
            arguments=arguments,
            caller=caller,
            timeout_ms=timeout_ms or descriptor.timeout_ms,
        )

        # 4. 构造 call_fn
        async def call_fn(**kwargs):
            if descriptor.provider == "tianyancha":
                return await self._call_tianyancha(descriptor, **kwargs)
            # 通用 HTTP 调用
            return await self._call_http(descriptor, **kwargs)

        # 5. 通过 invocation engine 执行
        return await self._invocation.call(
            request=request,
            descriptor=descriptor,
            call_fn=call_fn,
            **arguments,
        )

    # ── 直接按工具名调用 (调试/内部) ──────────

    async def call_by_name(
        self,
        tool_name: str,
        arguments: dict,
        *,
        caller: str = "",
        timeout_ms: int | None = None,
    ) -> MCPToolCallResult:
        """按具体工具名调用 (仅用于调试或内部工具)。

        Args:
            tool_name: 工具名，如 "tianyancha.baseinfo"
            arguments: 调用参数
            caller: 调用方
            timeout_ms: 覆盖默认超时

        Returns:
            MCPToolCallResult
        """
        descriptor = self.registry.get(tool_name)
        if descriptor is None:
            raise MCPToolError(
                tool_name=tool_name,
                category="not_found",
                message=f"Tool not registered: {tool_name}",
                retryable=False,
            )

        request = MCPToolCallRequest(
            tool_name=tool_name,
            arguments=arguments,
            caller=caller,
            timeout_ms=timeout_ms or descriptor.timeout_ms,
        )

        async def call_fn(**kwargs):
            return await self._call_http(descriptor, **kwargs)

        return await self._invocation.call(
            request=request,
            descriptor=descriptor,
            call_fn=call_fn,
            **arguments,
        )

    # ── 注册快捷方法 ─────────────────────────

    def register_tool(
        self,
        descriptor: MCPToolDescriptor,
        policy: MCPInvocationPolicy | None = None,
    ) -> None:
        """注册一个工具并绑定其策略。

        一步完成: registry.register + policy.register
        """
        self.registry.register(descriptor)
        if policy:
            self._policies.register_policy(policy)
        else:
            # 从 descriptor 自动生成策略
            auto_policy = MCPInvocationPolicy(
                tool_name=descriptor.name,
                max_timeout_ms=descriptor.timeout_ms,
                max_retries=descriptor.retry_count,
                rate_limit_per_minute=descriptor.rate_limit_per_minute,
            )
            self._policies.register_policy(auto_policy)

    # ── 内部: HTTP 调用实现 ───────────────────

    async def _call_http(self, descriptor: MCPToolDescriptor, **kwargs) -> dict:
        """通过 HTTP client 调用工具。

        当前为占位实现，天眼查接入后再完善。
        """
        # TODO: 天眼查 HTTP 接入
        raise NotImplementedError(
            f"HTTP call not yet implemented for tool: {descriptor.name}. "
            f"Provider: {descriptor.provider}"
        )

    async def _call_tianyancha(self, descriptor: MCPToolDescriptor, **kwargs) -> dict:
        """天眼查专用调用通道 (接入)。

        当前占位，等天眼查 SDK 装好后实装。
        """
        # TODO: 天眼查 SDK 接入
        raise NotImplementedError(
            "Tianyancha integration pending. "
            "Use the tianyancha_tool.py module directly for now."
        )
