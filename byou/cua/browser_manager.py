"""CUA Browser Manager — Playwright 浏览器操作封装。

为 ExecutionLayer 提供底层浏览器操作能力。
支持多 task 并发（每个 task_id 独立 page）。

依赖：playwright (pip install playwright)
浏览器：优先使用系统 Edge/Chrome，找不到再要求下载 Chromium
"""

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── BrowserManager ─────────────────────────────────────────────────────

class BrowserManager:
    """管理 Playwright 浏览器实例，为 CUA 执行层提供操作接口。

    每个 task_id 对应一个独立的 page（标签页），
    支持多任务并发执行。

    自动查找系统已有 Edge / Chrome，无需下载 Chromium。

    用法::
        bm = BrowserManager()
        await bm.launch()
        info = await bm.navigate("t1", "https://example.com")
        ok = await bm.click("t1", "text=Submit")
        await bm.close()
    """

    def __init__(self, headless: bool = True, executable_path: str | None = None):
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}   # task_id → Page
        self._headless = headless
        self._executable_path = executable_path

    # ── 生命周期 ─────────────────────────────────────────────────

    async def launch(self) -> None:
        """启动 Playwright + 浏览器（自动选择可用浏览器）。"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. "
                "Install: pip install playwright"
            )

        self._playwright = await async_playwright().start()

        # 1. 优先使用用户指定的浏览器路径
        if self._executable_path and Path(self._executable_path).exists():
            await self._launch_with_path(self._executable_path)
            logger.info("BrowserManager: launched with %s", self._executable_path)
            return

        # 2. 尝试 Playwright 自带的 Chromium（需提前下载）
        try:
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
            )
            logger.info("BrowserManager: launched (Playwright Chromium)")
            await self._create_context()
            return
        except Exception as exc:
            logger.warning("Playwright Chromium launch failed: %s", exc)

        # 3. 自动查找系统 Edge / Chrome
        system_browser = self.find_system_browser()
        if system_browser:
            await self._launch_with_path(system_browser)
            logger.info("BrowserManager: launched with system browser %s", system_browser)
            return

        raise RuntimeError(
            "无法启动浏览器。\n"
            "方案1：运行 `playwright install chromium` 下载 Chromium\n"
            "方案2：传入 executable_path 使用系统已有浏览器"
        )

    async def _launch_with_path(self, path: str) -> None:
        """使用指定路径的 Chromium-based 浏览器启动。"""
        self._browser = await self._playwright.chromium.launch(
            executable_path=path,
            headless=self._headless,
        )
        await self._create_context()

    async def _create_context(self) -> None:
        """创建浏览器上下文。"""
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._pages.clear()
        logger.info("BrowserManager: closed")

    # ── 系统浏览器查找 ────────────────────────────────────────────

    @staticmethod
    def find_system_browser() -> str | None:
        """自动查找系统已安装的 Edge / Chrome。"""
        if platform.system() != "Windows":
            # macOS / Linux：尝试常见路径
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/usr/bin/google-chrome",
                "/usr/bin/chromium",
                "/usr/bin/microsoft-edge",
            ]
        else:
            # Windows：Edge 和 Chrome 的常见安装路径
            program_files = [
                "C:\\Program Files\\",
                "C:\\Program Files (x86)\\",
            ]
            candidates = []
            for pf in program_files:
                candidates.append(pf + "Microsoft\\Edge\\Application\\msedge.exe")
                candidates.append(pf + "Google\\Chrome\\Application\\chrome.exe")

        for path in candidates:
            if Path(path).exists():
                logger.debug("Found system browser: %s", path)
                return path
        return None

    # ── Page 管理 ────────────────────────────────────────────────

    async def _get_page(self, task_id: str) -> Any:
        """获取（或创建）task 对应的 page。"""
        if task_id not in self._pages:
            if not self._context:
                raise RuntimeError("Browser not launched. Call launch() first.")
            self._pages[task_id] = await self._context.new_page()
            logger.debug("BrowserManager: created page for task %s", task_id)
        return self._pages[task_id]

    async def _close_page(self, task_id: str) -> None:
        page = self._pages.pop(task_id, None)
        if page:
            await page.close()
            logger.debug("BrowserManager: closed page for task %s", task_id)

    # ── 导航 ─────────────────────────────────────────────────────

    async def navigate(self, task_id: str, url: str, timeout: int = 30000) -> dict:
        """导航到指定 URL，返回页面元信息。"""
        page = await self._get_page(task_id)
        try:
            resp = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            title = await page.title()
            return {
                "url": page.url,
                "title": title,
                "status": resp.status if resp else None,
            }
        except Exception as exc:
            logger.warning("navigate(%s, %s) failed: %s", task_id, url, exc)
            raise

    async def refresh(self, task_id: str) -> dict:
        """刷新当前页面。"""
        page = await self._get_page(task_id)
        await page.reload(wait_until="domcontentloaded")
        return {"url": page.url, "title": await page.title()}

    # ── 点击 ─────────────────────────────────────────────────────

    async def click(self, task_id: str, target: str, timeout: int = 5000) -> bool:
        """点击元素。target 支持 Playwright 选择器语法。

        - "text=Submit"       → 按文字匹配
        - "#submit-btn"        → CSS ID 选择器
        - "button:has-text('OK')" → 组合选择器
        """
        page = await self._get_page(task_id)
        try:
            await page.click(target, timeout=timeout)
            return True
        except Exception as exc:
            logger.debug("click(%s, %s) failed: %s", task_id, target, exc)
            return False

    # ── 输入 ─────────────────────────────────────────────────────

    async def type_text(
        self, task_id: str, target: str, text: str, timeout: int = 5000,
    ) -> bool:
        """向输入框输入文字。先定位元素，再填入。"""
        page = await self._get_page(task_id)
        try:
            await page.wait_for_selector(target, timeout=timeout)
            await page.fill(target, text)
            return True
        except Exception as exc:
            logger.debug("type_text(%s, %s) failed: %s", task_id, target, exc)
            return False

    # ── 等待 ─────────────────────────────────────────────────────

    async def wait_for(
        self, task_id: str, target: str | None, timeout: int = 5000,
    ) -> bool:
        """等待元素出现（target 非空），或纯等待 timeout ms。"""
        page = await self._get_page(task_id)
        try:
            if target:
                await page.wait_for_selector(target, timeout=timeout)
            else:
                await asyncio.sleep(timeout / 1000.0)
            return True
        except Exception as exc:
            logger.debug("wait_for(%s, %s) timeout: %s", task_id, target, exc)
            return False

    # ── 滚动 ─────────────────────────────────────────────────────

    async def scroll(self, task_id: str, direction: str = "down") -> None:
        """滚动页面。direction: "up" | "down" """
        page = await self._get_page(task_id)
        delta = -400 if direction == "up" else 400
        await page.evaluate(f"window.scrollBy(0, {delta})")

    # ── 截图 ─────────────────────────────────────────────────────

    async def screenshot(self, task_id: str, path: str) -> bool:
        """对当前页面截图，保存到 path。"""
        page = await self._get_page(task_id)
        try:
            await page.screenshot(path=path)
            return True
        except Exception as exc:
            logger.warning("screenshot(%s) failed: %s", task_id, exc)
            return False

    # ── 页面状态 ────────────────────────────────────────────────

    async def get_page_state(self, task_id: str) -> dict:
        """返回当前页面状态（供 Perception 层使用）。"""
        page = await self._get_page(task_id)
        try:
            content = await page.content()
            return {
                "url": page.url,
                "title": await page.title(),
                "content": content[:2000],  # 截断，避免过大
                "dom_hash": str(hash(content[:5000])),
            }
        except Exception as exc:
            logger.warning("get_page_state(%s) failed: %s", task_id, exc)
            return {"url": "", "title": "", "content": "", "dom_hash": ""}

    # ── 上下文管理器 ─────────────────────────────────────────

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, *_):
        await self.close()
