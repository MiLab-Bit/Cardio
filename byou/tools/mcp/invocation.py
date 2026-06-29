"""MCP Tool Bus — 调用执行器。

Agent 不直接调用外部 API。
而是通过 ToolBus 发起调用，由 invocation 层做:
- 参数校验
- 鉴权注入
- 策略执行 (超时/重试/熔断)
- 审计日志
- 结构化错误映射
- 结果包装
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from byou.tools.mcp.types import (
    AuditEntry,
    AuditEventType,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolDescriptor,
    MCPToolError,
)
from byou.tools.mcp.errors import map_error
from byou.tools.mcp.policies import PolicyEngine
from byou.tools.mcp.client_manager import MCPClientManager
from byou.tools.mcp.auth import AuthProvider

logger = logging.getLogger(__name__)


class ToolInvocationEngine:
    """工具调用引擎 — MCP Tool Bus 的执行核心。

    连接 Registry, ClientManager, PolicyEngine, AuthProvider,
    为上层提供统一的 call() 接口。
    """

    def __init__(
        self,
        client_manager: MCPClientManager,
        policy_engine: PolicyEngine,
        auth_provider: AuthProvider,
    ):
        self._clients = client_manager
        self._policies = policy_engine
        self._auth = auth_provider

        # 审计缓冲区
        self._audit_buffer: list[AuditEntry] = []
        self._audit_lock = asyncio.Lock()

    async def call(
        self,
        request: MCPToolCallRequest,
        descriptor: MCPToolDescriptor,
        call_fn,
        *args,
        **kwargs,
    ) -> MCPToolCallResult:
        """执行一次工具调用。

        Args:
            request: 调用请求 (tool_name, arguments, caller, trace_id)
            descriptor: 工具的完整描述符
            call_fn: 实际执行的 async callable
            *args, **kwargs: 传给 call_fn

        Returns:
            MCPToolCallResult (成功) 或 MCPToolError (失败)

        调用流程:
        1. 参数校验
        2. 策略引擎前置检查 (熔断/限流)
        3. 执行 (带超时/重试)
        4. 结果包装
        5. 审计记录
        """
        tool_name = request.tool_name
        server_name = descriptor.server_name
        t_start = time.monotonic()

        # 0. 参数校验
        validation_err = self._validate_args(descriptor, request.arguments)
        if validation_err:
            return self._error_result(request, validation_err, t_start)

        # 1. 策略保护下执行
        try:
            await self._clients.begin_call(server_name)

            result_data = await self._policies.execute_with_policy(
                tool_name=tool_name,
                call_fn=call_fn,
                *args,
                **kwargs,
            )

            elapsed = (time.monotonic() - t_start) * 1000

            result = MCPToolCallResult(
                tool_name=tool_name,
                arguments=request.arguments,
                data=result_data,
                elapsed_ms=round(elapsed, 1),
                server_name=server_name,
            )

            # 审计
            await self._audit(AuditEventType.TOOL_CALL, result, None)
            await self._clients.end_call(server_name, success=True)

            return result

        except MCPToolError:
            # 策略引擎抛出的结构化错误 — 直接向上传递
            await self._clients.end_call(server_name, success=False)
            raise
        except Exception as e:
            elapsed = (time.monotonic() - t_start) * 1000
            error = map_error(tool_name, e)
            await self._clients.end_call(server_name, success=False)

            # 审计
            await self._audit(
                AuditEventType.TOOL_ERROR if error.category.value != "timeout" else AuditEventType.TOOL_TIMEOUT,
                None,
                error,
            )

            raise  # 重新抛出 → 由 Agent 层捕获

    def _validate_args(
        self, descriptor: MCPToolDescriptor, args: dict[str, Any],
    ) -> MCPToolError | None:
        """校验参数是否匹配 schema"""
        from byou.tools.mcp.types import ErrorCategory as EC
        for param in descriptor.parameters:
            if param.required and param.name not in args:
                return MCPToolError(
                    tool_name=descriptor.name,
                    category=EC.VALIDATION,
                    message=f"Missing required parameter: {param.name}",
                    retryable=False,
                )
            if param.name in args and param.type and param.enum:
                val = args[param.name]
                if val not in param.enum:
                    return MCPToolError(
                        tool_name=descriptor.name,
                        category=EC.VALIDATION,
                        message=f"Invalid value for {param.name}: {val}, expected one of {param.enum}",
                        retryable=False,
                    )
        return None

    @staticmethod
    def _error_result(request: MCPToolCallRequest, error: MCPToolError, t_start: float) -> MCPToolError:
        return error

    async def _audit(
        self,
        event_type: AuditEventType,
        result: MCPToolCallResult | None,
        error: MCPToolError | None,
    ) -> None:
        """记录审计日志"""
        entry = AuditEntry(
            event_type=event_type,
            tool_name=result.tool_name if result else (error.tool_name if error else ""),
            result="success" if result else "error",
            detail={},
        )
        async with self._audit_lock:
            self._audit_buffer.append(entry)
            # 缓冲 > 100 条时刷盘
            if len(self._audit_buffer) > 100:
                await self._flush_audit()

    async def _flush_audit(self) -> None:
        """刷盘审计日志 (TODO: 写入持久化存储)"""
        logger.info("Audit flush: %d records", len(self._audit_buffer))
        self._audit_buffer.clear()
