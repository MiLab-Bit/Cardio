"""
CUA Layer 3: State Modeling — 状态建模层

构建和维护操作状态模型：
- 当前页面状态追踪
- 操作历史状态机
- 预期状态 vs 实际状态比对
"""

import logging
from typing import Any
from enum import Enum

logger = logging.getLogger(__name__)


class PageState(Enum):
    """页面状态"""
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    PROCESSING = "processing"
    COMPLETE = "complete"


class StateModelingLayer:
    """
    状态建模层 — CUA 的第三层。

    追踪界面状态变化，维护操作状态机，
    检测预期状态与实际状态的不一致。
    """

    def __init__(self):
        self._state_history: list[dict] = []
        self._current_state: dict = {}
        self._expected_state: dict = {}

    async def process(self, semantic_result: dict, context: Any) -> dict:
        """
        构建当前操作状态模型。

        Args:
            semantic_result: Semantic Align 层的输出
            context: CUA 执行上下文

        Returns:
            {
                "page_state": str,
                "form_state": dict,
                "navigation_path": list[str],
                "state_diff": dict,
                "anomalies": list[str],
            }
        """
        logger.debug("CUA State Modeling: 状态建模")

        elements = semantic_result.get("semantic_elements", [])
        text = semantic_result.get("text_summary", "")

        # 判断当前页面状态
        page_state = self._detect_page_state(elements, text)

        # 检测状态异常
        anomalies = self._detect_anomalies(elements, context)

        # 构建状态模型
        state_model = {
            "page_state": page_state,
            "element_count": len(elements),
            "interactive_elements": len([e for e in elements if e.get("enabled")]),
            "error_present": any("error" in str(e).lower() for e in elements),
            "navigation_path": context.memory.get("navigation_path", []),
            "state_diff": self._compute_state_diff(),
            "anomalies": anomalies,
        }

        # 记录状态历史
        self._state_history.append(state_model)
        self._current_state = state_model

        return state_model

    def _detect_page_state(self, elements: list[dict], text: str) -> str:
        """检测页面状态"""
        if not elements and not text:
            return PageState.LOADING.value

        # 检测错误页面
        error_keywords = ["error", "错误", "500", "404", "not found"]
        if any(kw in text.lower() for kw in error_keywords):
            return PageState.ERROR.value

        # 检测加载中
        loading_keywords = ["loading", "加载中", "请稍候"]
        if any(kw in text.lower() for kw in loading_keywords):
            return PageState.LOADING.value

        return PageState.READY.value

    def _detect_anomalies(self, elements: list[dict], context: Any) -> list[str]:
        """检测状态异常"""
        anomalies = []

        # 检查是否有预期但未找到的元素
        if self._expected_state:
            expected_elements = self._expected_state.get("elements", [])
            current_texts = {e.get("text", "") for e in elements}
            for expected in expected_elements:
                if expected.get("text") and expected["text"] not in current_texts:
                    anomalies.append(f"预期元素未出现: {expected['text']}")

        # 检查是否卡在同一页面
        if len(self._state_history) >= 3:
            recent = self._state_history[-3:]
            if all(
                s.get("page_state") == PageState.READY.value
                and s.get("element_count") == recent[0].get("element_count")
                for s in recent
            ):
                anomalies.append("页面连续3步无变化，可能卡住")

        return anomalies

    def set_expected_state(self, expected: dict) -> None:
        """设置预期状态（供验证层使用）"""
        self._expected_state = expected

    def _compute_state_diff(self) -> dict:
        """计算状态变化差异"""
        if len(self._state_history) < 2:
            return {"changed": False}

        prev = self._state_history[-2]
        curr = self._current_state or {}

        return {
            "changed": True,
            "element_count_diff": curr.get("element_count", 0) - prev.get("element_count", 0),
            "page_state_changed": prev.get("page_state") != curr.get("page_state"),
        }

    def get_navigation_path(self) -> list[str]:
        """获取导航路径"""
        return [s.get("page_state", "unknown") for s in self._state_history]

    def is_ready(self) -> bool:
        return True
