"""
CUA Layer 2: Semantic Alignment — 语义对齐层（SLM 升级版）

将感知层的原始元素映射到业务语义：
- SLM 驱动的自然语言 → 元素映射
- 模糊匹配与语义理解（替代纯关键词）
- 多语言支持（中英文混合指令）
"""

from __future__ import annotations

import json
import logging
from typing import Any

from byou.core.model_router import ModelRouter

logger = logging.getLogger(__name__)

# ── 系统提示 ─────────────────────────────────────────────────────
# 让 SLM 做「任务描述 → 页面元素」的语义对齐

ALIGN_PROMPT = """\
You are a UI element matcher. Given a task description and a list of page elements,
return a JSON array mapping each action in the task to the best-matching element(s).

Task description (in Chinese or English):
{task}

Page elements (from browser perception layer):
{elements}

For each action in the task, find the best matching element(s) from the list.
Consider: element type, text, placeholder, aria-label, and semantic meaning.

Output ONLY a JSON array (no markdown fencing), each item:
{
  "action":  "<action description from task>",
  "element_index":  <index in elements list, or null if not found>,
  "confidence":  <0.0-1.0>,
  "reason":  "<why this element matches>"
}

If no element matches well (confidence < 0.4), set element_index to null.
"""


class SemanticAlignLayer:
    """
    语义对齐层 — CUA 的第二层。

    将 Perception 层输出的原始 UI 元素映射为有意义的业务概念，
    使用 SLM 做语义理解，使 Planner 能够以自然语言方式理解界面。
    """

    def __init__(self, model_router: ModelRouter | None = None):
        # 关键词降级映射（SLM 不可用时的 fallback）
        self._keyword_map = {
            "搜索":   ["search", "查找", "查询", "input[type=search]"],
            "登录":   ["login", "sign in", "signin", "登录"],
            "提交":   ["submit", "send", "confirm", "确认", "提交", "ok"],
            "下一页": ["next", "下一页", ">", "›", "more"],
            "关闭":   ["close", "cancel", "dismiss", "×", "关闭"],
            "输入":   ["input", "textarea", "文本框", "输入框"],
            "点击":   ["button", "link", "a", "btn"],
        }
        self._model_router = model_router
        # 是否优先使用 SLM（可在运行时切换）
        self.use_slm = model_router is not None

    def set_model_router(self, router: ModelRouter) -> None:
        self._model_router = router
        self.use_slm = True

    async def process(self, perception_result: dict, context: Any) -> dict:
        """
        语义对齐：将 UI 元素映射到业务语义。

        Args:
            perception_result: Perception 层的输出
            context: CUA 执行上下文（含 task 描述）

        Returns:
            {
                "semantic_elements": list[dict],
                "intent_matches":   list[dict],
                "confidence":        float,
                "alignment_method":  "slm" | "keyword",
            }
        """
        elements = perception_result.get("elements", [])
        task_desc = ""
        if context and hasattr(context, "task"):
            task_desc = context.task.get("description", "") if isinstance(context.task, dict) else str(context.task)

        # ── 尝试 SLM 语义对齐 ────────────────────────────────
        slm_result = None
        if self.use_slm and self._model_router and task_desc:
            try:
                slm_result = await self._align_with_slm(task_desc, elements)
            except Exception as e:
                logger.warning("SLM alignment failed, falling back to keyword: %s", e)

        # ── 构建 semantic_elements ─────────────────────────────
        semantic_elements = []
        for i, elem in enumerate(elements):
            sem_elem = {
                **elem,
                "semantic_type": self._classify_element(elem),
                "intent": self._infer_intent(elem),
                "actions": self._available_actions(elem),
            }
            # 如果 SLM 返回了对齐结果，附加匹配信息
            if slm_result and i in (m.get("element_index") for m in slm_result):
                match = next(m for m in slm_result if m.get("element_index") == i)
                sem_elem["slm_match"] = {
                    "action": match["action"],
                    "confidence": match["confidence"],
                    "reason": match["reason"],
                }
            semantic_elements.append(sem_elem)

        # ── intent_matches ─────────────────────────────────────
        intent_matches = self._build_intent_matches(
            semantic_elements, slm_result, task_desc
        )

        confidence = (
            0.9 if slm_result else 0.7
        )

        method = "slm" if slm_result else "keyword"
        logger.debug("Semantic Align: method=%s, elements=%d", method, len(semantic_elements))

        return {
            "semantic_elements": semantic_elements,
            "text_summary": perception_result.get("text_content", "")[:500],
            "intent_matches": intent_matches,
            "confidence": confidence,
            "alignment_method": method,
        }

    # ── SLM 对齐 ────────────────────────────────────────────

    async def _align_with_slm(self, task_desc: str, elements: list[dict]) -> list[dict] | None:
        """
        使用 SLM 做任务描述 → 页面元素的语义对齐。

        Returns:
            List of {action, element_index, confidence, reason}
            or None if SLM fails.
        """
        if not elements:
            return []

        # 截断元素列表（避免超 token 限制）
        max_elems = 30
        elem_slice = elements[:max_elems]
        elem_descriptions = []
        for i, e in enumerate(elem_slice):
            desc = f"[{i}] type={e.get('type','?')}"
            if e.get("text"):
                desc += f" text='{e['text'][:40]}'"
            if e.get("placeholder"):
                desc += f" placeholder='{e['placeholder'][:30]}'"
            if e.get("aria_label"):
                desc += f" aria='{e['aria_label'][:30]}'"
            elem_descriptions.append(desc)

        prompt = ALIGN_PROMPT.format(
            task=task_desc,
            elements="\n".join(elem_descriptions),
        )

        # 使用 ModelRouter 的 CHEAP 层（对齐任务很简单）
        from byou.config import get_settings
        settings = get_settings()
        # 直接调用 OpenAI API（用 CHEAP 模型）
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
            model = settings.get_model_for_tier("cheap")
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
            )
            content = response.choices[0].message.content.strip()
            # 去掉可能的 markdown 代码块
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()
            result = json.loads(content)
            if isinstance(result, list):
                return result
        except Exception as e:
            logger.warning("SLM align call failed: %s", e)
            return None

    # ── 降级：关键词分类 ────────────────────────────────────

    def _classify_element(self, element: dict) -> str:
        elem_type = element.get("type", "").lower()
        text = (element.get("text") or "").lower()
        placeholder = (element.get("placeholder") or "").lower()

        if elem_type == "input":
            if any(w in text + placeholder for w in ["password", "密码"]):
                return "password_input"
            if any(w in text + placeholder for w in ["search", "搜索", "查找"]):
                return "search_input"
            return "text_input"
        elif elem_type == "button":
            if any(w in text for w in ["提交", "确认", "submit", "confirm", "ok", "保存", "发布"]):
                return "submit_button"
            return "action_button"
        elif elem_type == "link":
            return "navigation_link"
        elif elem_type == "table":
            return "data_table"
        return elem_type or "unknown"

    def _infer_intent(self, element: dict) -> str:
        text = (element.get("text") or "").lower()
        placeholder = (element.get("placeholder") or "").lower()
        combined = text + " " + placeholder
        for intent, keywords in self._keyword_map.items():
            if any(kw in combined for kw in keywords):
                return intent
        return "interact"

    def _available_actions(self, element: dict) -> list[str]:
        elem_type = element.get("type", "").lower()
        return {"button": ["click"], "input": ["type", "clear", "fill"], "link": ["click", "hover"], "textarea": ["type", "clear"]}.get(elem_type, ["click"])

    def _build_intent_matches(
        self,
        elements: list[dict],
        slm_result: list[dict] | None,
        task_desc: str,
    ) -> list[dict]:
        """构建 intent → element 匹配列表。"""
        matches = []
        if slm_result:
            # 用 SLM 结果
            for m in slm_result:
                idx = m.get("element_index")
                if idx is not None and idx < len(elements):
                    elem = elements[idx]
                    matches.append({
                        "action": m["action"],
                        "element_type": elem.get("type"),
                        "element_text": elem.get("text", "")[:60],
                        "confidence": m.get("confidence", 0.5),
                        "method": "slm",
                        "reason": m.get("reason", ""),
                    })
        else:
            # 降级：关键词匹配
            for elem in elements:
                intent = elem.get("intent", "interact")
                if intent != "interact":
                    matches.append({
                        "action": intent,
                        "element_type": elem.get("type"),
                        "element_text": elem.get("text", "")[:60],
                        "confidence": 0.6,
                        "method": "keyword",
                        "reason": f"关键词匹配: {intent}",
                    })
        return matches

    def is_ready(self) -> bool:
        return True
