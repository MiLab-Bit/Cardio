"""MCP Tool Bus — 工具注册中心。

核心抽象: Tool Registry。
管理所有已注册工具的声明周期: 注册、发现、过滤、启停、权限隔离。
Agent 不直接依赖具体工具名，而是通过 capability 发现可用工具。
"""

from __future__ import annotations

import logging
from collections import defaultdict

from byou.tools.mcp.types import (
    MCPToolDescriptor,
    ToolCapability,
    ToolCategory,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册中心 — Byou 的工具总线入口。

    所有外部工具通过 registry 注册后，Agent 才能发现和调用。

    Usage:
        reg = ToolRegistry()
        reg.register(tool_descriptor)

        # Agent 按 capability 发现
        tools = reg.find_by_capability(ToolCapability.COMPANY_LOOKUP)

        # Agent 按分类发现
        tools = reg.find_by_category(ToolCategory.BUSINESS_DATA)

        # 获取所有可用工具名
        names = reg.list_tool_names()
    """

    def __init__(self):
        # 主索引: tool_name → MCPToolDescriptor
        self._tools: dict[str, MCPToolDescriptor] = {}

        # 二级索引: capability → [tool_name, ...]
        self._by_capability: dict[ToolCapability, list[str]] = defaultdict(list)

        # 二级索引: category → [tool_name, ...]
        self._by_category: dict[ToolCategory, list[str]] = defaultdict(list)

        # 二级索引: server → [tool_name, ...]
        self._by_server: dict[str, list[str]] = defaultdict(list)

        # 二级索引: provider → [tool_name, ...]
        self._by_provider: dict[str, list[str]] = defaultdict(list)

        # 动态状态
        self._disabled: set[str] = set()          # 被禁用的工具名
        self._env_filter: dict[str, set[str]] = defaultdict(set)  # env → 禁用的工具

        # Agent 权限映射: agent_name → allowed_capabilities
        self._agent_permissions: dict[str, set[ToolCapability]] = {}

    # ── 注册 / 注销 ──────────────────────────

    def register(self, tool: MCPToolDescriptor) -> None:
        """注册一个工具描述符。

        如果 key 已存在 → 覆盖更新。
        自动维护所有二级索引。
        """
        old = self._tools.get(tool.name)

        # 清旧索引
        if old:
            self._unindex(old)

        # 存主索引
        self._tools[tool.name] = tool

        # 建二级索引
        self._index(tool)

        logger.info("Tool registered: %s (caps=%s, cat=%s)", tool.name, tool.capabilities, tool.category)

    def unregister(self, name: str) -> None:
        """注销一个工具"""
        tool = self._tools.pop(name, None)
        if tool:
            self._unindex(tool)
            self._disabled.discard(name)
            logger.info("Tool unregistered: %s", name)

    def _index(self, tool: MCPToolDescriptor) -> None:
        for cap in tool.capabilities:
            self._by_capability[cap].append(tool.name)
        if tool.category:
            self._by_category[tool.category].append(tool.name)
        if tool.server_name:
            self._by_server[tool.server_name].append(tool.name)
        if tool.provider:
            self._by_provider[tool.provider].append(tool.name)

    def _unindex(self, tool: MCPToolDescriptor) -> None:
        for cap in tool.capabilities:
            lst = self._by_capability.get(cap, [])
            if tool.name in lst:
                lst.remove(tool.name)
        for cat_lst in self._by_category.values():
            if tool.name in cat_lst:
                cat_lst.remove(tool.name)
        for srv_lst in self._by_server.values():
            if tool.name in srv_lst:
                srv_lst.remove(tool.name)

    # ── 发现 / 查询 ──────────────────────────

    def get(self, name: str) -> MCPToolDescriptor | None:
        """按名称获取工具描述符"""
        return self._tools.get(name)

    def find_by_capability(
        self,
        capability: ToolCapability,
        environment: str = "production",
        include_disabled: bool = False,
    ) -> list[MCPToolDescriptor]:
        """按能力标签发现工具 (Agent 推荐方式)。

        Agent 不应该写死工具名，而应该声明需要的能力。
        """
        names = self._by_capability.get(capability, [])
        return self._filter(names, environment, include_disabled)

    def find_by_category(
        self,
        category: ToolCategory,
        environment: str = "production",
    ) -> list[MCPToolDescriptor]:
        """按分类查找工具"""
        names = self._by_category.get(category, [])
        return self._filter(names, environment)

    def find_by_server(self, server_name: str) -> list[MCPToolDescriptor]:
        """查找某 server 的所有工具"""
        names = self._by_server.get(server_name, [])
        return [t for t in map(self._tools.get, names) if t is not None]

    def list_all(
        self,
        environment: str = "production",
        include_disabled: bool = False,
    ) -> list[MCPToolDescriptor]:
        """列出所有注册工具"""
        return self._filter(list(self._tools.keys()), environment, include_disabled)

    def list_tool_names(self, environment: str = "production") -> list[str]:
        """列出所有可用工具名"""
        tools = self.list_all(environment=environment)
        return [t.name for t in tools]

    def _filter(
        self,
        names: list[str],
        environment: str,
        include_disabled: bool = False,
    ) -> list[MCPToolDescriptor]:
        """过滤: 启用状态 + 环境匹配"""
        result: list[MCPToolDescriptor] = []
        for name in names:
            tool = self._tools.get(name)
            if not tool:
                continue
            if not include_disabled and name in self._disabled:
                continue
            if environment not in tool.environments:
                continue
            result.append(tool)
        # 按优先级降序
        result.sort(key=lambda t: -t.priority)
        return result

    # ── 优先级 fallback ──────────────────────

    def get_best_tool(
        self,
        capability: ToolCapability,
        environment: str = "production",
    ) -> MCPToolDescriptor | None:
        """获取某个 cap 下优先级最高的可用工具。

        ResearcherAgent 声明 "我需要 COMPANY_LOOKUP"，
        registry 返回优先级最高的工具。
        """
        candidates = self.find_by_capability(capability, environment)
        return candidates[0] if candidates else None

    # ── 动态启停 ─────────────────────────────

    def disable(self, name: str, reason: str = "") -> None:
        """禁用一个工具"""
        if name in self._tools:
            self._disabled.add(name)
            logger.info("Tool disabled: %s (reason=%s)", name, reason)

    def enable(self, name: str) -> None:
        """重新启用"""
        self._disabled.discard(name)

    def is_enabled(self, name: str) -> bool:
        return name in self._tools and name not in self._disabled

    # ── 环境隔离 ─────────────────────────────

    def disable_for_env(self, name: str, env: str) -> None:
        """在特定环境禁用某工具"""
        self._env_filter[env].add(name)

    def enable_for_env(self, name: str, env: str) -> None:
        self._env_filter[env].discard(name)

    # ── Agent 权限 ────────────────────────────

    def grant_agent(self, agent_name: str, capabilities: set[ToolCapability]) -> None:
        """授权 Agent 使用某些能力"""
        self._agent_permissions[agent_name] = capabilities

    def agent_can_use(self, agent_name: str, capability: ToolCapability) -> bool:
        """检查 Agent 是否有使用权。

        安全策略: 未显式授权 → 默认拒绝。
        必须通过 grant_agent 显式授权每个 Agent 可以使用的 capability。
        """
        caps = self._agent_permissions.get(agent_name)
        if caps is None:
            return False  # 未配置 → 默认拒绝 (白名单策略)
        return capability in caps

    # ── 统计 ─────────────────────────────────

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def active_tool_count(self) -> int:
        return len([n for n in self._tools if n not in self._disabled])
