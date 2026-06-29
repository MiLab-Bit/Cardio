"""Browser Execution Subsystem — Session Manager.

管理 Playwright BrowserSession 的生命周期:
- 创建/复用浏览器会话
- Tab 管理
- Context 隔离
- 会话状态追踪
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from byou.tools.browser.types import (
    BrowserSessionInfo,
    BrowserSessionState,
)

logger = logging.getLogger(__name__)

# 默认浏览器配置
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class BrowserSession:
    """单个浏览器会话 — 封装 Playwright Browser + Context。

    一个 Session = 一个 BrowserContext，可复用跨多个 BrowserTask。
    """

    def __init__(
        self,
        session_id: str,
        *,
        headless: bool = True,
        user_agent: str = DEFAULT_USER_AGENT,
        viewport: dict[str, int] | None = None,
    ):
        self.session_id = session_id
        self._headless = headless
        self._user_agent = user_agent
        self._viewport = viewport or {"width": 1280, "height": 900}

        # Playwright 对象 (延迟初始化)
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[int, Any] = {}   # tab_index → Page
        self._active_tab_index: int = 0

        # 状态
        self.state = BrowserSessionState.IDLE
        self._created_at = time.monotonic()
        self._last_activity = time.monotonic()
        self._total_tasks = 0
        self._total_pages = 0
        self._total_errors = 0

    # ── 生命周期 ───────────────────────────────

    async def start(self) -> None:
        """启动浏览器会话"""
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            self._context = await self._browser.new_context(
                user_agent=self._user_agent,
                viewport=self._viewport,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            self._pages[0] = await self._context.new_page()
            self._active_tab_index = 0
            self.state = BrowserSessionState.IDLE
            self._touch_activity()

            logger.info("Session %s started (headless=%s)", self.session_id, self._headless)

        except Exception as e:
            self.state = BrowserSessionState.CLOSED
            logger.error("Session %s start failed: %s", self.session_id, e)
            raise

    async def close(self) -> None:
        """关闭浏览器会话"""
        self.state = BrowserSessionState.CLOSING
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning("Session %s close error: %s", self.session_id, e)
        finally:
            self.state = BrowserSessionState.CLOSED
            logger.info("Session %s closed", self.session_id)

    # ── Tab 管理 ────────────────────────────────

    @property
    def active_page(self) -> Any:
        """当前活跃 Page 对象"""
        return self._pages.get(self._active_tab_index)

    async def new_tab(self, url: str = "about:blank") -> int:
        """新建 Tab, 返回 tab_index"""
        page = await self._context.new_page()
        idx = max(self._pages.keys(), default=-1) + 1
        self._pages[idx] = page
        if url != "about:blank":
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        self._active_tab_index = idx
        self._touch_activity()
        return idx

    async def switch_tab(self, tab_index: int) -> Any:
        """切换到指定 Tab"""
        page = self._pages.get(tab_index)
        if not page:
            raise ValueError(f"Tab {tab_index} not found")
        await page.bring_to_front()
        self._active_tab_index = tab_index
        self._touch_activity()
        return page

    async def close_tab(self, tab_index: int) -> None:
        """关闭指定 Tab"""
        page = self._pages.pop(tab_index, None)
        if page:
            await page.close()
            # 如果关闭的是活跃 tab, 切换到下一个
            if tab_index == self._active_tab_index and self._pages:
                self._active_tab_index = min(self._pages.keys())

    # ── 统计 ────────────────────────────────────

    def increment_task(self) -> None:
        self._total_tasks += 1

    def increment_page(self) -> None:
        self._total_pages += 1

    def increment_error(self) -> None:
        self._total_errors += 1

    def mark_blocked(self) -> None:
        self.state = BrowserSessionState.BLOCKED

    def _touch_activity(self) -> None:
        self._last_activity = time.monotonic()

    def snapshot(self) -> BrowserSessionInfo:
        """生成会话快照"""
        active_url = ""
        if self.active_page:
            try:
                active_url = self.active_page.url
            except Exception:
                pass

        return BrowserSessionInfo(
            session_id=self.session_id,
            state=self.state,
            created_at=self._created_at,  # type: ignore
            last_activity=self._last_activity,  # type: ignore
            tab_count=len(self._pages),
            active_tab_url=active_url,
            total_tasks=self._total_tasks,
            total_pages=self._total_pages,
            total_errors=self._total_errors,
            headless=self._headless,
            user_agent=self._user_agent,
        )


class BrowserSessionManager:
    """管理所有浏览器会话的池。

    - 按 session_id 复用或创建
    - 空闲会话超时自动清理
    - 限制最大并行会话数
    """

    def __init__(self, max_sessions: int = 3, idle_timeout_s: int = 300):
        self._sessions: dict[str, BrowserSession] = {}
        self._max_sessions = max_sessions
        self._idle_timeout_s = idle_timeout_s

    async def get_session(
        self,
        session_id: str = "",
        *,
        headless: bool = True,
        reuse: bool = True,
    ) -> BrowserSession:
        """获取或创建会话"""
        # 复用已有
        if reuse and session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if session.state in (BrowserSessionState.IDLE, BrowserSessionState.ACTIVE):
                logger.debug("Reusing session %s", session_id)
                return session
            # 旧会话已关闭 → 清理
            await self._cleanup_closed()

        # 限制并行数
        active = [s for s in self._sessions.values()
                  if s.state in (BrowserSessionState.IDLE, BrowserSessionState.ACTIVE)]
        if len(active) >= self._max_sessions:
            # 清理空闲会话
            await self._cleanup_idle()
            if len(active) >= self._max_sessions:
                raise RuntimeError(f"Max sessions ({self._max_sessions}) reached")

        # 创建新会话
        sid = session_id or f"browser-{len(self._sessions)}"
        session = BrowserSession(sid, headless=headless)
        await session.start()
        self._sessions[sid] = session
        return session

    async def close_session(self, session_id: str) -> None:
        """关闭指定会话"""
        session = self._sessions.pop(session_id, None)
        if session:
            await session.close()

    async def close_all(self) -> None:
        """关闭所有会话"""
        for s in list(self._sessions.values()):
            await s.close()
        self._sessions.clear()

    async def _cleanup_closed(self) -> None:
        """清理已关闭的会话"""
        closed = [k for k, v in self._sessions.items() if v.state == BrowserSessionState.CLOSED]
        for k in closed:
            self._sessions.pop(k, None)

    async def _cleanup_idle(self) -> None:
        """清理超时空闲会话"""
        now = time.monotonic()
        for k, v in list(self._sessions.items()):
            if v.state == BrowserSessionState.IDLE:
                idle_s = now - v._last_activity
                if idle_s > self._idle_timeout_s:
                    logger.info("Cleaning idle session %s (idle for %.0fs)", k, idle_s)
                    await self.close_session(k)

    def list_sessions(self) -> list[BrowserSessionInfo]:
        """列出所有会话状态"""
        return [s.snapshot() for s in self._sessions.values()]
