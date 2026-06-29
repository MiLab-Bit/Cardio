"""Byou Rust 扩展兼容层。

自动检测 `_byou_rust` 是否可用，
可用时走 Rust 实现（快 5-10x），
不可用走纯 Python 实现（功能完全一致）。

用法:
    from byou._rust_compat import ComplexityClassifier, extract_fields_rust

    classifier = ComplexityClassifier()
    tier, reason, conf = classifier.classify(prompt)

    result_json = extract_fields_rust(ocr_text)
"""

from __future__ import annotations

import json
from typing import Any

# ── 尝试导入 Rust 扩展 ──────────────────────────────────────────────────────────

_HAS_RUST = False
_RUST_ERROR = None

try:
    import _byou_rust  # noqa: F401 — maturin 编译的扩展

    _HAS_RUST = True
except ImportError as _e:
    _RUST_ERROR = _e
    _byou_rust = None  # type: ignore


# ── ComplexityClassifier 兼容层 ──────────────────────────────────────────────────

class ComplexityClassifier:
    """LLM 调用复杂度分类器 — Rust 优先，Python 降级。"""

    def __init__(self):
        if _HAS_RUST:
            self._rs = _byou_rust.ComplexityClassifierRs()  # type: ignore
            self._use_rust = True
        else:
            self._use_rust = False
            # Python 降级: 复用现有逻辑
            self.deep_keywords = {
                "分析", "总结", "比较", "评估", "推理", "规划",
                "analyze", "summarize", "compare", "evaluate",
                "深度", "详细", "全面", "复杂",
                "代码", "编程", "算法", "架构",
            }
            self.medium_keywords = {
                "写", "生成", "创建", "列出", "解释", "改",
                "write", "generate", "list", "explain",
            }
            self.cheap_keywords = {
                "是", "是什么", "what", "how many", "多少", "吗",
            }

    def classify(self, prompt: str, tools: list[str] | None = None,
                 history_turns: int = 0) -> tuple[str, str, float]:
        if self._use_rust:
            return self._rs.classify(prompt, tools or [], history_turns)  # type: ignore

        # Python 降级实现 (与 Rust 逻辑对齐)
        prompt_lower = prompt.lower()
        word_count = len(prompt.split())
        char_count = len(prompt)

        if tools and len(tools) >= 5:
            return "deep", "many tools", 0.8
        if history_turns >= 10:
            return "deep", "long history", 0.7

        for kw in self.deep_keywords:
            if kw in prompt_lower:
                return "deep", f"keyword: {kw}", 0.85

        for kw in self.medium_keywords:
            if kw in prompt_lower:
                return "medium", f"keyword: {kw}", 0.7

        for kw in self.cheap_keywords:
            if kw in prompt_lower:
                return "cheap", f"keyword: {kw}", 0.9

        if char_count <= 20 or word_count <= 5:
            return "cheap", "short prompt", 0.6
        if char_count >= 200 or word_count >= 50:
            return "medium", "long prompt", 0.6

        return "medium", "default", 0.5


# ── FieldExtractor 兼容层 ───────────────────────────────────────────────────────

def extract_fields_rust(ocr_text: str) -> dict[str, Any]:
    """从 OCR 文本提取名片字段 — Rust 优先，Python 降级。

    Args:
        ocr_text: OCR 识别的纯文本（多行）

    Returns:
        dict: 与 FieldCandidates.to_llm_prompt_dict() 格式对齐
    """
    if _HAS_RUST:
        result_json = _byou_rust.extract_fields_from_text_rs(ocr_text)  # type: ignore
        return json.loads(result_json)

    # Python 降级: 调用现有的 FieldExtractor
    from byou.tools.ocr.ocr_field_extractor import FieldExtractor, OCRDocument

    # 构造最小 OCRDocument
    doc = OCRDocument(full_text=ocr_text, lines=[], engine_name="fallback")
    extractor = FieldExtractor()
    candidates = extractor.extract(doc)
    return candidates.to_llm_prompt_dict()


def extract_fields_rust_from_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """从 OCR 行列表提取字段（含坐标信息）。

    Args:
        lines: [{"text": ..., "center_x": ..., "center_y": ..., "confidence": ...}]

    Returns:
        dict: 提取结果
    """
    if _HAS_RUST:
        lines_json = json.dumps(lines, ensure_ascii=False)
        result_json = _byou_rust.extract_fields_rs(lines_json)  # type: ignore
        return json.loads(result_json)

    # Python 降级
    from byou.tools.ocr.ocr_field_extractor import FieldExtractor, OCRDocument, OCRLine

    ocr_lines = [
        OCRLine(
            text=l["text"],
            bbox=[0, 0, 0, 0],
            center_x=l.get("center_x", 0),
            center_y=l.get("center_y", 0),
            confidence=l.get("confidence", 0),
            line_index=i,
        )
        for i, l in enumerate(lines)
    ]
    doc = OCRDocument(
        full_text="\n".join(l["text"] for l in lines),
        lines=ocr_lines,
        engine_name="fallback",
    )
    extractor = FieldExtractor()
    candidates = extractor.extract(doc)
    return candidates.to_llm_prompt_dict()


# ── 公开查询 ─────────────────────────────────────────────────────────────────────

def rust_available() -> bool:
    """返回 Rust 扩展是否可用。"""
    return _HAS_RUST


def rust_error() -> Exception | None:
    """返回 Rust 导入失败的原因（如果有的话）。"""
    return _RUST_ERROR
