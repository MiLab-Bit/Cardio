"""MCP Tool Bus — 客户端管理器。

管理所有 MCP server 的连接、会话、调用生命周期。
不为每次调用创建新连接，维护连接池。
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from byou.tools.mcp.types import (
    MCPServerConfig,
    MCPServerType,
    MCPSessionInfo,
    MCPSessionState,
    CircuitState,
)

logger = logging.getLogger(__name__)


class MCPClientManager:
    """MCP 客户端管理器 — 连接池 + 会话生命周期。

    设计决策:
    - 每个 MCP server 维护连接池 (可配置 max_connections)
    - HTTP server: httpx.AsyncClient 单例 (自带连接池)
    - STDIO server: 子进程管理 (按需启动/停止)
    - WebSocket: 长连接, 自动重连
    - 会话状态追踪: 活跃调用数、错误数、最后活跃时间
    """

    def __init__(self):
        # server_name → 会话信息
        self._sessions: dict[str, MCPSessionInfo] = {}

        # server_name → httpx.AsyncClient (HTTP 模式)
        self._http_clients: dict[str, "httpx.AsyncClient"] = {}

        # server_name → 子进程句柄 (STDIO 模式)
        self._stdio_processes: dict[str, "asyncio.subprocess.Process"] = {}

        # server_name → WebSocket 连接 (WebSocket 模式)
        self._ws_connections: dict[str, object] = {}

        # 写保护锁
        self._lock = asyncio.Lock()

    # ── 会话管理 ──────────────────────────────

    def get_session(self, server_name: str) -> MCPSessionInfo:
        """获取当前会话快照"""
        session = self._sessions.get(server_name)
        if session is None:
            session = MCPSessionInfo(server_name=server_name)
            self._sessions[server_name] = session
        return session

    async def connect(self, config: MCPServerConfig) -> MCPSessionInfo:
        """建立与 MCP server 的连接"""
        async with self._lock:
            session = self.get_session(config.name)

            if config.server_type == MCPServerType.HTTP:
                return await self._connect_http(config, session)
            elif config.server_type == MCPServerType.EMBEDDED:
                return self._connect_embedded(config, session)
            elif config.server_type == MCPServerType.STDIO:
                return await self._connect_stdio(config, session)
            elif config.server_type == MCPServerType.WEBSOCKET:
                return await self._connect_websocket(config, session)
            elif config.server_type == MCPServerType.SDK_WRAPPER:
                return self._connect_sdk_wrapper(config, session)

            return session

    async def disconnect(self, server_name: str) -> None:
        """断开与 server 的连接"""
        async with self._lock:
            session = self._sessions.pop(server_name, None)

            # 关闭 HTTP 客户端
            client = self._http_clients.pop(server_name, None)
            if client:
                await client.aclose()

            # 终止 STDIO 子进程
            proc = self._stdio_processes.pop(server_name, None)
            if proc:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    proc.kill()

            if session:
                session.state = MCPSessionState.CLOSED
                session.last_activity = None

            logger.info("Disconnected from MCP server: %s", server_name)

    async def disconnect_all(self) -> None:
        """断开所有连接"""
        for name in list(self._sessions.keys()):
            await self.disconnect(name)

    # ── HTTP 连接 ────────────────────────────

    async def _connect_http(self, config: MCPServerConfig, session: MCPSessionInfo) -> MCPSessionInfo:
        if config.name not in self._http_clients:
            import httpx
            client = httpx.AsyncClient(
                base_url=config.base_url,
                timeout=httpx.Timeout(config.connect_timeout_ms / 1000),
                limits=httpx.Limits(max_connections=config.max_connections),
            )
            self._http_clients[config.name] = client

        session.state = MCPSessionState.ACTIVE
        session.last_activity = time.monotonic()
        logger.info("HTTP MCP server connected: %s → %s", config.name, config.base_url)
        return session

    def _connect_embedded(self, config: MCPServerConfig, session: MCPSessionInfo) -> MCPSessionInfo:
        """嵌入式 server — 在同一进程中运行，无需网络连接。"""
        session.state = MCPSessionState.ACTIVE
        session.last_activity = time.monotonic()
        return session

    async def _connect_stdio(self, config: MCPServerConfig, session: MCPSessionInfo) -> MCPSessionInfo:
        """启动 MCP 子进程 (STDIO 模式)"""
        proc = await asyncio.create_subprocess_exec(
            *config.command.split(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        self._stdio_processes[config.name] = proc
        session.state = MCPSessionState.ACTIVE
        session.last_activity = time.monotonic()
        return session

    async def _connect_websocket(self, config: MCPServerConfig, session: MCPSessionInfo) -> MCPSessionInfo:
        """WebSocket 连接 — 未来实现"""
        session.state = MCPSessionState.ACTIVE
        session.last_activity = time.monotonic()
        logger.warning("WebSocket MCP not yet implemented for %s", config.name)
        return session

    def _connect_sdk_wrapper(self, config: MCPServerConfig, session: MCPSessionInfo) -> MCPSessionInfo:
        """SDK 包装 — 如天眼查，直接导入 SDK 调用"""
        session.state = MCPSessionState.ACTIVE
        session.last_activity = time.monotonic()
        return session

    # ── 调用计数 ─────────────────────────────

    async def begin_call(self, server_name: str) -> None:
        """标记一次调用开始"""
        async with self._lock:
            session = self.get_session(server_name)
            session.active_calls += 1
            session.total_calls += 1
            session.state = MCPSessionState.ACTIVE
            session.last_activity = time.monotonic()

    async def end_call(self, server_name: str, success: bool = True) -> None:
        """标记一次调用结束"""
        async with self._lock:
            session = self.get_session(server_name)
            session.active_calls = max(0, session.active_calls - 1)
            session.last_activity = time.monotonic()
            if not success:
                session.total_errors += 1
            if session.active_calls == 0:
                session.state = MCPSessionState.IDLE

    # ── 工具信息 ─────────────────────────────

    async def list_tools(self, server_name: str) -> list[dict]:
        """从 server 获取工具列表 (MCP protocol list_tools)"""
        # TODO: 实现 MCP 协议的 tools/list
        return []

    # ── 获取 HTTP Client ─────────────────────

    def get_http_client(self, server_name: str):
        """获取 HTTP client (用于 SDK_WRAPPER/HTTP 模式的网络调用)"""
        return self._http_clients.get(server_name)

    # ── 枚举会话 ─────────────────────────────

    def active_sessions(self) -> list[MCPSessionInfo]:
        """获取所有活跃会话"""
        return [
            s for s in self._sessions.values()
            if s.state not in (MCPSessionState.CLOSED,)
        ]
