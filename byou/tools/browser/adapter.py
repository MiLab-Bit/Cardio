"""Browser Execution Subsystem — ResearcherAgent Adapter.

将 BrowserTaskExecutor 暴露为 ResearcherAgent 可用的声明式接口。
同时提供 MCP Tool Bus capability 注册点。

ResearcherAgent 视角:
    result = await self.browser.research_company_website("阿里巴巴", "https://www.alibaba.com")
    → 返回 BrowserExecutionReport

MCP Tool Bus 视角:
    注册 capability=BROWSER_AUTOMATE
    工具名=browser.execute_task
"""

from __future__ import annotations

import logging
from typing import Any

from byou.tools.browser.types import (
    BrowserAction,
    BrowserActionType,
    BrowserExecutionReport,
    BrowserSelectorType,
    BrowserTask,
    ExtractedPageData,
    PageSnapshot,
    ResearchFinding,
    ResearchMode,
)
from byou.tools.browser.executor import BrowserTaskExecutor

logger = logging.getLogger(__name__)


class BrowserResearchAdapter:
    """ResearcherAgent 的浏览器研究适配器。

    将 ResearcherAgent 的研究需求翻译为 BrowserTask，
    再交给 BrowserTaskExecutor 执行。

    三种研究模式:
    1. research_company_website() — 公司官网研究
    2. search_and_research() — 搜索引擎驱动
    3. targeted_research() — 指定站点定向
    """

    def __init__(self, executor: BrowserTaskExecutor | None = None):
        self._executor = executor or BrowserTaskExecutor()

    # ── 模式 1: 公司官网研究 ─────────────────────

    async def research_company_website(
        self,
        company_name: str,
        website_url: str,
        *,
        max_depth: int = 2,
        headless: bool = True,
        session_id: str = "",
    ) -> BrowserExecutionReport:
        """打开公司官网，提取: 公司简介、产品/服务、联系方式、新闻动态。

        Args:
            company_name: 公司名称
            website_url: 官网 URL
            max_depth: 最多深入几层链接
            headless: 是否无头模式
            session_id: 复用会话 ID
        """
        actions: list[BrowserAction] = [
            BrowserAction(
                action_type=BrowserActionType.NAVIGATE,
                description=f"打开 {company_name} 官网",
                value=website_url,
                step_index=0,
                wait_for_navigation=True,
                timeout_ms=20_000,
            ),
            BrowserAction(
                action_type=BrowserActionType.SCROLL,
                description="滚动页面加载内容",
                value="500",
                step_index=1,
                wait_after_ms=1000,
            ),
            BrowserAction(
                action_type=BrowserActionType.EXTRACT,
                description="提取首页核心内容",
                step_index=2,
            ),
        ]

        # 常见官网子页面
        sub_pages = ["/about", "/about-us", "/contact", "/products"]
        for i, sub in enumerate(sub_pages, start=len(actions)):
            if max_depth >= 2:
                actions.append(BrowserAction(
                    action_type=BrowserActionType.NAVIGATE,
                    description=f"访问子页面: {sub}",
                    value=f"{website_url.rstrip('/')}{sub}",
                    step_index=i,
                    timeout_ms=15_000,
                    continue_on_failure=True,  # 子页面不存在不终止
                    retry_on_failure=False,
                ))
                actions.append(BrowserAction(
                    action_type=BrowserActionType.EXTRACT,
                    description=f"提取 {sub} 页面内容",
                    step_index=i + 1,
                ))

        task = BrowserTask(
            task_id=f"company-{company_name}",
            mode=ResearchMode.COMPANY_WEBSITE,
            description=f"研究 {company_name} 官网 ({website_url})",
            target_url=website_url,
            actions=actions,
            max_steps=len(actions) + 2,
            max_depth=max_depth,
            max_total_time_ms=90_000,
            headless=headless,
            session_id=session_id,
            reuse_session=bool(session_id),
            allowed_domains=[website_url.split("/")[2]] if "://" in website_url else [],
            caller="researcher",
        )

        return await self._executor.execute(task)

    # ── 模式 2: 搜索引擎驱动 ─────────────────────

    async def search_and_research(
        self,
        query: str,
        *,
        search_engine: str = "https://www.bing.com/search?q=",
        max_results: int = 5,
        headless: bool = True,
        session_id: str = "",
    ) -> BrowserExecutionReport:
        """搜索 + 逐个打开结果页面研究。

        Args:
            query: 搜索关键词
            search_engine: 搜索引擎 URL 模板
            max_results: 最多打开几个结果
            headless: 是否无头模式
        """
        import urllib.parse
        search_url = search_engine + urllib.parse.quote(query)

        actions: list[BrowserAction] = [
            BrowserAction(
                action_type=BrowserActionType.NAVIGATE,
                description=f"搜索: {query}",
                value=search_url,
                step_index=0,
                wait_for_navigation=True,
                timeout_ms=15_000,
            ),
            BrowserAction(
                action_type=BrowserActionType.WAIT,
                description="等待搜索结果加载",
                wait_after_ms=3000,
                step_index=1,
            ),
            BrowserAction(
                action_type=BrowserActionType.EXTRACT,
                description="提取搜索结果",
                step_index=2,
            ),
        ]

        task = BrowserTask(
            task_id=f"search-{query[:30]}",
            mode=ResearchMode.SEARCH_DRIVEN,
            description=f"搜索并研究: {query}",
            target_url=search_url,
            search_query=query,
            actions=actions,
            max_steps=15,
            max_total_time_ms=60_000,
            headless=headless,
            session_id=session_id,
            reuse_session=bool(session_id),
            caller="researcher",
        )

        return await self._executor.execute(task)

    # ── 模式 3: 指定站点定向 ─────────────────────

    async def targeted_research(
        self,
        urls: list[str],
        *,
        description: str = "",
        headless: bool = True,
        session_id: str = "",
    ) -> BrowserExecutionReport:
        """打开指定的一组 URL，逐个提取内容。

        Args:
            urls: 目标 URL 列表
            description: 任务描述
            headless: 是否无头模式
        """
        actions: list[BrowserAction] = []
        for i, url in enumerate(urls):
            actions.append(BrowserAction(
                action_type=BrowserActionType.NAVIGATE,
                description=f"打开: {url}",
                value=url,
                step_index=i * 2,
                timeout_ms=20_000,
                continue_on_failure=True,
            ))
            actions.append(BrowserAction(
                action_type=BrowserActionType.EXTRACT,
                description=f"提取: {url}",
                step_index=i * 2 + 1,
            ))

        task = BrowserTask(
            task_id=f"targeted-{len(urls)}urls",
            mode=ResearchMode.TARGETED_DOMAIN,
            description=description or f"定向研究 {len(urls)} 个页面",
            target_urls=urls,
            actions=actions,
            max_steps=len(urls) * 3,
            max_total_time_ms=120_000,
            headless=headless,
            session_id=session_id,
            reuse_session=bool(session_id),
            caller="researcher",
        )

        return await self._executor.execute(task)

    # ── Session 管理 ─────────────────────────────

    def get_session_status(self) -> list[dict[str, Any]]:
        """获取所有浏览器会话状态"""
        infos = self._executor._session_manager.list_sessions()
        return [info.model_dump(mode="json") for info in infos]

    async def close_all(self) -> None:
        """关闭所有浏览器会话"""
        await self._executor._session_manager.close_all()
