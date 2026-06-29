"""CUA Perception — 感知层（含语义对齐）

通过 Playwright 真实检测页面 DOM，输出带语义标签的结构化元素描述。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 动作-元素关键词映射 ──────────────────────────────────────

_ACTION_KEYWORD_MAP: dict[str, list[str]] = {
    "搜索": ["search", "find", "input[type=search]"],
    "登录": ["login", "signin", "sign-in"],
    "提交": ["submit", "send", "confirm", "ok"],
    "下一页": ["next", ">", "›"],
    "关闭": ["close", "cancel", "dismiss", "×"],
}


class PerceptionLayer:
    """感知层 — 从浏览器 DOM 或上下文提取结构化界面描述。

    集成语义对齐：每个元素自动标注 semantic_type / intent / available_actions。
    """

    def __init__(self, browser_manager: Any = None):
        self.browser = browser_manager

    def set_browser(self, browser_manager: Any) -> None:
        self.browser = browser_manager

    async def process(self, task: Any, context: Any) -> dict:
        if self.browser and task.target_url:
            return await self._from_browser(task, context)
        return await self._from_context(task, context)

    # ── 浏览器真实感知 ──────────────────────────────────────

    async def _from_browser(self, task: Any, context: Any) -> dict:
        try:
            info = await self.browser.get_page_info(task.id)
            raw_elements = await self.browser.extract_elements(task.id)
            text = await self.browser.extract_text(task.id)
            screenshot_ref = f"memory://{task.id}/screenshot"
            context.screenshots.append(screenshot_ref)

            elements = [self._enrich(e) for e in raw_elements]
            text_lower = text.lower()

            return {
                "url": info["url"],
                "title": info["title"],
                "elements": elements,
                "text_content": text[:5000],
                "screenshot_ref": screenshot_ref,
                "viewport": info.get("viewport", {"width": 1920, "height": 1080}),
                "element_count": len(elements),
                "visible_count": sum(1 for e in elements if e.get("visible")),
                "source": "playwright",
                # ── 合并语义对齐输出 ──
                "page_state": _detect_page_state(text_lower),
                "intent_matches": _find_intent_matches(elements),
            }
        except Exception as e:
            logger.warning("Playwright 感知失败，回退: %s", e)
            return await self._from_context(task, context)

    # ── 上下文回退 ──────────────────────────────────────────

    async def _from_context(self, task: Any, context: Any) -> dict:
        prev = context.current_state.get("perception", {})
        return {
            "url": task.target_url or prev.get("url", ""),
            "title": prev.get("title", ""),
            "elements": [],
            "text_content": prev.get("text_content", ""),
            "screenshot_ref": context.screenshots[-1] if context.screenshots else "",
            "viewport": {"width": 1920, "height": 1080},
            "source": "context_fallback",
            "page_state": "unknown",
            "intent_matches": [],
        }

    # ── 语义对齐（内联） ─────────────────────────────────────

    @staticmethod
    def _enrich(element: dict) -> dict:
        text = (element.get("text", "") or "").lower()
        elem_type = (element.get("type", "") or "").lower()
        return {
            **element,
            "semantic_type": _classify(elem_type, text),
            "intent": _infer_intent(text),
            "available_actions": {"button": ["click"], "input": ["type", "clear"],
                                   "link": ["click", "hover"]}.get(elem_type, ["click"]),
        }

    def is_ready(self) -> bool:
        # FIX: `or True` made this always return True — removed.
        # Now correctly reports whether browser manager is attached.
        return self.browser is not None


# ── 内联辅助（原 SemanticAlign + StateModeling） ──────────────

def _classify(elem_type: str, text: str) -> str:
    if elem_type == "input" and "password" in text:
        return "password_input"
    if elem_type == "input":
        return "text_input"
    if elem_type == "button" and any(w in text for w in ("提交", "确认", "submit", "confirm", "ok")):
        return "submit_button"
    if elem_type == "button":
        return "action_button"
    if elem_type == "link":
        return "navigation_link"
    if elem_type == "table":
        return "data_table"
    return elem_type or "unknown"


def _infer_intent(text: str) -> str:
    for intent, keywords in _ACTION_KEYWORD_MAP.items():
        if any(kw in text for kw in keywords):
            return intent
    return "interact"


def _find_intent_matches(elements: list[dict]) -> list[dict]:
    return [{"element": e.get("type"), "text": e.get("text"), "intent": e.get("intent"),
             "confidence": 0.7} for e in elements if e.get("intent") != "interact"]


def _detect_page_state(text_lower: str) -> str:
    if not text_lower:
        return "loading"
    if any(kw in text_lower for kw in ("error", "500", "404", "not found")):
        return "error"
    if any(kw in text_lower for kw in ("loading", "加载中", "请稍候")):
        return "loading"
    return "ready"
