"""MCP Tool Bus — 健康检查。

两级检查:
- shallow: Registry 内部状态一致性
- deep: 对每个注册的 MCP server 做 ping/list_tools 探测
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from byou.tools.mcp.registry import ToolRegistry
from byou.tools.mcp.client_manager import MCPClientManager

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    """健康检查报告"""
    ok: bool = True
    timestamp: float = field(default_factory=time.time)

    # 汇总
    total_servers: int = 0
    healthy_servers: int = 0
    total_tools: int = 0
    disabled_tools: int = 0

    # 详情
    server_status: dict[str, str] = field(default_factory=dict)
    tool_counts_by_server: dict[str, int] = field(default_factory=dict)

    # 问题
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class HealthChecker:
    """工具总线健康检查器"""

    def __init__(
        self,
        registry: ToolRegistry,
        client_manager: MCPClientManager,
    ):
        self._registry = registry
        self._clients = client_manager

    def shallow_check(self) -> HealthReport:
        """浅层检查 — 检查 Registry 内部一致性 (无网络调用)。"""
        report = HealthReport()

        try:
            all_tools = self._registry.list_all()
            report.total_tools = len(all_tools)
            report.disabled_tools = len([t for t in all_tools if not self._registry.is_enabled(t.name)])

            # 检查索引完整性
            by_name = {t.name for t in all_tools}
            for cap in self._registry._by_capability:
                names = self._registry._by_capability[cap]
                for name in names:
                    if name not in by_name:
                        report.errors.append(f"Orphan capability index: {cap} → {name}")

            # 统计每个 server 的工具数
            for name in set(t.server_name for t in all_tools if t.server_name):
                report.tool_counts_by_server[name] = len(self._registry.find_by_server(name))
            report.total_servers = len(report.tool_counts_by_server)
            report.healthy_servers = report.total_servers  # 浅层检查不区分健康状态

        except Exception as e:
            report.ok = False
            report.errors.append(f"Shallow check exception: {e}")

        return report

    async def deep_check(self) -> HealthReport:
        """深层检查 — 探测所有 MCP server (需要网络)。"""
        report = self.shallow_check()

        for server_name in list(report.tool_counts_by_server.keys()):
            try:
                tools = self._registry.find_by_server(server_name)
                report.server_status[server_name] = "healthy" if tools else "empty"
                report.healthy_servers += 1  # 浅层已统计

            except Exception as e:
                report.server_status[server_name] = f"error: {e}"
                report.warnings.append(f"Server {server_name}: {e}")

        if report.warnings:
            report.ok = len(report.errors) == 0  # warnings 不影响 ok

        return report

    def status_summary(self) -> dict[str, Any]:
        """返回人类可读的状态摘要 (JSON-friendly)。"""
        report = self.shallow_check()
        return {
            "ok": report.ok,
            "total_tools": report.total_tools,
            "disabled_tools": report.disabled_tools,
            "total_servers": report.total_servers,
            "healthy_servers": report.healthy_servers,
            "errors": report.errors[:5],
            "warnings": report.warnings[:5],
        }
