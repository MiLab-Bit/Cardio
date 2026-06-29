"""
Browser Manager — Playwright 浏览器自动化管理

管理浏览器生命周期，提供页面池、截图、元素提取等能力。
默认使用系统 Edge 浏览器 (channel="msedge")，无需额外安装 Chromium。
"""

import asyncio
import logging
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserManager:
    """Playwright 浏览器管理器。

    特性：
    - 使用系统 Edge 浏览器 (无需额外下载 Chromium)
    - 页面池管理（每任务一页）
    - 自动清理
    - 截图与 DOM 元素提取
    """

    def __init__(
        self,
        channel: str = "msedge",
        headless: bool = True,
        viewport: Optional[dict] = None,
    ):
        self.channel = channel
        self.headless = headless
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self._playwright: Any = None
        self._browser: Any = None
        self._pages: dict[str, Any] = {}
        self._started = False

    async def start(self) -> None:
        """启动浏览器。幂等操作。"""
        if self._started:
            return

        from playwright.async_api import async_playwright

        logger.info("启动 Playwright (channel=%s, headless=%s)", self.channel, self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            channel=self.channel,
            headless=self.headless,
        )
        self._started = True
        logger.info("浏览器已启动")

    async def get_page(self, task_id: str) -> Any:
        """获取或创建任务的页面。"""
        if not self._started:
            await self.start()

        if task_id not in self._pages:
            page = await self._browser.new_page()
            await page.set_viewport_size(self.viewport)
            self._pages[task_id] = page
            logger.debug("创建新页面: task=%s", task_id)

        return self._pages[task_id]

    async def close_page(self, task_id: str) -> None:
        """关闭任务页面。"""
        page = self._pages.pop(task_id, None)
        if page:
            await page.close()
            logger.debug("关闭页面: task=%s", task_id)

    async def navigate(
        self, task_id: str, url: str, timeout: int = 30000
    ) -> dict:
        """导航到 URL，返回页面元信息。"""
        page = await self.get_page(task_id)
        response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else 0,
        }

    async def screenshot(self, task_id: str, path: Optional[str] = None) -> bytes:
        """截取页面截图。如提供 path 则保存到文件。"""
        page = await self.get_page(task_id)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=path, full_page=False)
        return await page.screenshot()

    async def extract_elements(self, task_id: str) -> list[dict]:
        """通过 JS 提取页面中所有可交互元素。"""
        page = await self.get_page(task_id)

        elements = await page.evaluate("""() => {
            const selectors = 'button, a, input, select, textarea, [role="button"], [onclick]';
            const results = [];
            const nodes = document.querySelectorAll(selectors);
            for (let i = 0; i < Math.min(nodes.length, 200); i++) {
                const el = nodes[i];
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                const visible = style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    rect.width > 0 && rect.height > 0;
                results.push({
                    index: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || el.tagName.toLowerCase(),
                    id: el.id || '',
                    className: (el.className && typeof el.className === 'string')
                        ? el.className : '',
                    text: (el.textContent || '').trim().substring(0, 200),
                    placeholder: el.placeholder || '',
                    href: el.href || '',
                    name: el.name || '',
                    role: el.getAttribute('role') || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    visible: visible,
                    enabled: !el.disabled,
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                            w: Math.round(rect.width), h: Math.round(rect.height) },
                    selector: el.id ? '#' + el.id :
                        (el.className && typeof el.className === 'string'
                            ? '.' + el.className.split(' ')[0] : el.tagName)
                });
            }
            return results;
        }""")
        return elements

    async def extract_text(self, task_id: str) -> str:
        """提取页面可见文本。"""
        page = await self.get_page(task_id)
        text = await page.evaluate(
            "() => (document.body?.innerText || '').substring(0, 10000)"
        )
        return text

    async def get_page_info(self, task_id: str) -> dict:
        """获取页面基本信息（url, title, viewport）。"""
        page = await self.get_page(task_id)
        return {
            "url": page.url,
            "title": await page.title(),
            "viewport": self.viewport,
        }

    # ── 交互操作 ────────────────────────────────────────

    async def click(
        self, task_id: str, selector: str, timeout: int = 5000
    ) -> bool:
        """点击元素。返回是否成功。"""
        page = await self.get_page(task_id)
        try:
            await page.click(selector, timeout=timeout)
            return True
        except Exception as e:
            logger.warning("点击失败: selector=%s, error=%s", selector, e)
            return False

    async def type_text(
        self, task_id: str, selector: str, text: str, timeout: int = 5000
    ) -> bool:
        """在输入框中填入文本。"""
        page = await self.get_page(task_id)
        try:
            await page.fill(selector, text, timeout=timeout)
            return True
        except Exception as e:
            logger.warning("输入失败: selector=%s, error=%s", selector, e)
            return False

    async def wait_for(
        self,
        task_id: str,
        selector: Optional[str] = None,
        timeout: int = 5000,
    ) -> bool:
        """等待元素出现，或纯延时。返回是否等到。"""
        page = await self.get_page(task_id)
        if selector:
            try:
                await page.wait_for_selector(selector, timeout=timeout)
                return True
            except Exception:
                return False
        else:
            await page.wait_for_timeout(timeout)
            return True

    async def scroll(
        self, task_id: str, direction: str = "down", amount: int = 500
    ) -> None:
        """滚动页面。"""
        page = await self.get_page(task_id)
        dy = amount if direction == "down" else -amount
        await page.evaluate(f"window.scrollBy(0, {dy})")

    async def refresh(self, task_id: str) -> None:
        """刷新当前页面。"""
        page = await self.get_page(task_id)
        await page.reload(wait_until="domcontentloaded")

    async def evaluate(self, task_id: str, expression: str) -> Any:
        """在页面上下文中执行 JS 表达式。"""
        page = await self.get_page(task_id)
        return await page.evaluate(expression)

    # ── 生命周期 ────────────────────────────────────────

    async def stop(self) -> None:
        """关闭所有页面和浏览器。"""
        for task_id in list(self._pages.keys()):
            await self.close_page(task_id)

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._started = False
        logger.info("浏览器已关闭")

    @property
    def active_page_count(self) -> int:
        return len(self._pages)
