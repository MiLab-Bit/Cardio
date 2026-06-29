"""OCR 数据模型 — Byou OCR 子系统强类型输出。

设计原则:
- 适合传给 LLM 做字段解析（文本+位置+置信度）
- 支持名片字段抽取前的原始保留
- 支持低置信度区域标记
- 支持中英文混排
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── 引擎信息 ────────────────────────────────────

class OCREngineInfo(BaseModel):
    """OCR 引擎元信息"""
    name: str = ""                      # "PaddleOCR" / "CnOCR" / "TrOCR"
    version: str = ""                   # "PP-OCRv4" / "DTrOCR-v3" / "trocr-base"
    languages: list[str] = Field(default_factory=list)
    gpu_accelerated: bool = False


# ── 文字行 ──────────────────────────────────────

class OCRPoint(BaseModel):
    """二维坐标点"""
    x: float = 0.0
    y: float = 0.0


class OCRLine(BaseModel):
    """单行文字识别结果 — OCR 的最小输出单元"""
    text: str = ""                      # 识别文本
    confidence: float = 0.0             # 行级置信度 [0, 1]
    bbox: list[OCRPoint] = Field(       # 四边形包围框 (4顶点，左上起顺时针)
        default_factory=list,
        min_length=0,
        max_length=4,
    )
    language: str = "unknown"           # "ch" / "en" / "mixed" / "digit"
    is_vertical: bool = False           # 是否竖排文本
    source_engine: str = ""             # 由哪个引擎识别（用于多引擎 trace）

    @property
    def center_y(self) -> float:
        pts = [p.y for p in self.bbox] if self.bbox else []
        return sum(pts) / len(pts) if pts else 0.0

    @property
    def center_x(self) -> float:
        pts = [p.x for p in self.bbox] if self.bbox else []
        return sum(pts) / len(pts) if pts else 0.0

    @property
    def height(self) -> float:
        if len(self.bbox) < 4:
            return 0.0
        return abs(self.bbox[3].y - self.bbox[0].y)

    def is_low_confidence(self, threshold: float = 0.7) -> bool:
        return self.confidence < threshold


# ── 文字块 ──────────────────────────────────────

class OCRBlock(BaseModel):
    """文字区块: 一个逻辑区域内的多行文字"""
    block_id: int = 0
    block_type: Literal["text", "table", "figure", "formula", "unknown"] = "text"
    lines: list[OCRLine] = Field(default_factory=list)
    bbox: list[OCRPoint] = Field(default_factory=list)
    avg_confidence: float = 0.0
    merged_from: list[int] = Field(default_factory=list)  # 合并前的块ID (版面归并追溯)

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    @property
    def center_y(self) -> float:
        pts = [p.y for p in self.bbox] if self.bbox else []
        return sum(pts) / len(pts) if pts else 0.0

    @property
    def center_x(self) -> float:
        pts = [p.x for p in self.bbox] if self.bbox else []
        return sum(pts) / len(pts) if pts else 0.0

    @property
    def block_height(self) -> float:
        ys = [p.y for p in self.bbox] if self.bbox else [0, 0]
        return max(ys) - min(ys) if ys else 0.0

    def recalc_confidence(self) -> None:
        if self.lines:
            self.avg_confidence = sum(l.confidence for l in self.lines) / len(self.lines)


# ── 元数据 & 置信度报告 ─────────────────────────

class OCRMetadata(BaseModel):
    """OCR 执行元数据"""
    engine: str = ""
    fallback_level: int = 0
    fallback_chain: list[str] = Field(default_factory=list)
    total_time_ms: float = 0.0
    image_size: tuple[int, int] = (0, 0)
    image_format: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class ConfidenceReport(BaseModel):
    """置信度评估报告"""
    overall: float = 0.0
    per_block: dict[int, float] = Field(default_factory=dict)
    per_line: dict[str, float] = Field(default_factory=dict)  # key → 行文本前20字符
    low_confidence_blocks: list[int] = Field(default_factory=list)
    low_confidence_lines: list[str] = Field(default_factory=list)
    suggestion: Literal["pass", "fallback", "manual_review"] = "pass"


# ── 文档 ────────────────────────────────────────

class OCRDocument(BaseModel):
    """OCR 完整输出文档 — Byou OCR 子系统最终产物

    这是 ExtractorAgent 接收的唯一 OCR 输出。
    """

    # 原始文本
    full_text: str = ""

    # 结构化
    blocks: list[OCRBlock] = Field(default_factory=list)

    # 引擎
    engine_name: str = ""
    engine_info: OCREngineInfo | None = None
    fallback_level: int = 0

    # 置信度
    overall_confidence: float = 0.0
    confidence_report: ConfidenceReport | None = None

    # 元数据
    metadata: OCRMetadata = Field(default_factory=OCRMetadata)
    source_path: str = ""

    # 扩展
    warnings: list[str] = Field(default_factory=list)
    raw_response: Any = None             # 引擎原始输出 (调试用)

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    @property
    def lines(self) -> list[OCRLine]:
        """展平所有行（按阅读顺序）"""
        result: list[OCRLine] = []
        for block in sorted(self.blocks, key=lambda b: (b.center_y, b.center_x)):
            result.extend(block.lines)
        return result

    @property
    def is_reliable(self) -> bool:
        return self.overall_confidence >= 0.85

    def get_low_confidence_lines(self, threshold: float = 0.7) -> list[OCRLine]:
        return [l for l in self.lines if l.is_low_confidence(threshold)]

    def to_llm_context(self) -> dict[str, Any]:
        """转成 LLM prompt 可直接消费的格式"""
        return {
            "full_text": self.full_text,
            "line_count": len(self.lines),
            "block_count": len(self.blocks),
            "low_confidence_lines": [
                {"text": l.text, "confidence": round(l.confidence, 2)}
                for l in self.get_low_confidence_lines()
            ],
            "engine": self.engine_name,
            "overall_confidence": round(self.overall_confidence, 2),
            "source": self.source_path,
        }
