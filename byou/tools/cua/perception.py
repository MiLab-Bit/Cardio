"""
CUA Layer 1: Perception — 感知层

通过 Playwright 真实检测页面 DOM：
- UI 元素检测与定位
- 文本内容提取
- 页面截图
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PerceptionLayer:
    """感知层 — CUA 的第一层。

    通过 Playwright BrowserManager 获取真实页面状态，
    将原始 DOM 转化为结构化的元素描述。
    """

    def __init__(self, browser_manager: Optional[Any] = None):
        self.browser = browser_manager
        self.supported_elements = [
            "button", "input", "link", "image", "text",
            "dropdown", "checkbox", "table", "form", "dialog",
        ]

    def set_browser(self, browser_manager: Any) -> None:
        """注入浏览器管理器。"""
        self.browser = browser_manager

    async def process(self, task: Any, context: Any) -> dict:
        """感知当前界面状态。

        如果有 Playwright 浏览器，则从真实 DOM 提取；
        否则回退到上下文中的历史数据。
        """
        logger.debug("CUA Perception: 感知界面状态")

        if self.browser and task.target_url:
            return await self._perceive_from_browser(task, context)
        else:
            return await self._perceive_from_context(task, context)

    async def _perceive_from_browser(self, task: Any, context: Any) -> dict:
        """通过 Playwright 真实感知页面。"""
        try:
            info = await self.browser.get_page_info(task.id)
            elements = await self.browser.extract_elements(task.id)
            text = await self.browser.extract_text(task.id)
            screenshot_bytes = await self.browser.screenshot(task.id)

            # 存储截图引用到上下文
            screenshot_ref = f"memory://{task.id}/screenshot"
            context.memory["last_screenshot"] = screenshot_ref
            context.screenshots.append(screenshot_ref)

            return {
                "url": info["url"],
                "title": info["title"],
                "elements": elements,
                "text_content": text[:5000],
                "screenshot_ref": screenshot_ref,
                "viewport": info["viewport"],
                "element_count": len(elements),
                "visible_element_count": sum(
                    1 for e in elements if e.get("visible")
                ),
                "source": "playwright",
            }
        except Exception as e:
            logger.warning("Playwright 感知失败，回退到上下文: %s", e)
            return await self._perceive_from_context(task, context)

    async def _perceive_from_context(self, task: Any, context: Any) -> dict:
        """回退模式：从历史上下文推断。"""
        prev_state = context.current_state.get("perception", {})
        return {
            "url": task.target_url or prev_state.get("url", ""),
            "title": prev_state.get("title", ""),
            "elements": prev_state.get("elements", []),
            "text_content": prev_state.get("text_content", ""),
            "screenshot_ref": (
                context.screenshots[-1] if context.screenshots else ""
            ),
            "viewport": {"width": 1920, "height": 1080},
            "source": "context_fallback",
        }

    def is_ready(self) -> bool:
        return True
