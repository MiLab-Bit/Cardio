"""
CUA Layer 2: Semantic Alignment — 语义对齐层

将感知层的原始元素映射到业务语义：
- UI 元素 → 业务动作映射
- 模糊匹配与语义理解
- 多语言支持
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SemanticAlignLayer:
    """
    语义对齐层 — CUA 的第二层。

    将 Perception 层输出的原始 UI 元素映射为有意义的业务概念，
    使 Planner 能够以自然语言方式理解界面。
    """

    def __init__(self):
        # 预定义的动作-元素映射
        self._action_map = {
            "搜索": ["search", "find", "input[type=search]"],
            "登录": ["login", "signin", "sign-in"],
            "提交": ["submit", "send", "confirm", "ok"],
            "下一页": ["next", "下一页", ">", "›"],
            "关闭": ["close", "cancel", "dismiss", "×"],
        }

    async def process(self, perception_result: dict, context: Any) -> dict:
        """
        语义对齐：将 UI 元素映射到业务语义。

        Args:
            perception_result: Perception 层的输出
            context: CUA 执行上下文

        Returns:
            {
                "semantic_elements": list[dict],
                "intent_matches": list[dict],
                "confidence": float,
            }
        """
        logger.debug("CUA Semantic Align: 语义对齐")

        elements = perception_result.get("elements", [])
        text_content = perception_result.get("text_content", "")

        semantic_elements = []
        for elem in elements:
            semantic_elements.append({
                **elem,
                "semantic_type": self._classify_element(elem),
                "intent": self._infer_intent(elem),
                "actions": self._available_actions(elem),
            })

        return {
            "semantic_elements": semantic_elements,
            "text_summary": text_content[:500],
            "intent_matches": self._find_intent_matches(semantic_elements),
            "confidence": 0.8,
        }

    def _classify_element(self, element: dict) -> str:
        """分类界面元素"""
        elem_type = element.get("type", "").lower()
        text = element.get("text", "").lower()

        if elem_type == "input" and "password" in text:
            return "password_input"
        elif elem_type == "input":
            return "text_input"
        elif elem_type == "button" and any(
            w in text for w in ["提交", "确认", "submit", "confirm", "ok"]
        ):
            return "submit_button"
        elif elem_type == "button":
            return "action_button"
        elif elem_type == "link":
            return "navigation_link"
        elif elem_type == "table":
            return "data_table"

        return elem_type or "unknown"

    def _infer_intent(self, element: dict) -> str:
        """推断元素意图"""
        text = element.get("text", "").lower()
        for intent, keywords in self._action_map.items():
            if any(kw.lower() in text for kw in keywords):
                return intent
        return "interact"

    def _available_actions(self, element: dict) -> list[str]:
        """元素可用的操作列表"""
        elem_type = element.get("type", "").lower()
        actions = {"button": ["click"], "input": ["type", "clear"], "link": ["click", "hover"]}
        return actions.get(elem_type, ["click"])

    def _find_intent_matches(self, elements: list[dict]) -> list[dict]:
        """找到与当前任务意图匹配的元素"""
        matches = []
        for elem in elements:
            if elem.get("intent") != "interact":
                matches.append({
                    "element": elem.get("type"),
                    "text": elem.get("text"),
                    "intent": elem.get("intent"),
                    "confidence": 0.7,
                })
        return matches

    def is_ready(self) -> bool:
        return True
