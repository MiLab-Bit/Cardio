"""Cardio Temporal 跨边界数据类。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalyzeInput:
    """客户分析工作流输入。"""
    raw_text: str = ""
    raw_type: str = "text"  # text | card_image | dialogue
    provider: dict[str, Any] | None = None
