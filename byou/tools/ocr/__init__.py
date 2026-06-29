"""byou.tools.ocr — Byou OCR 子系统。

提供:
- OCRPipeline: 完整 OCR 管线 (预处理→检测→识别→置信度评估→输出)
- OCRDocument: 强类型 OCR 输出文档
- PaddleOCRProvider: PP-OCRv4 主力引擎
- CnOCRProvider: DTrOCR 中文 fallback
- OCRRouter: 自动选路 + 多级降级

Quick start:
    from byou.tools.ocr import OCRPipeline

    pipeline = OCRPipeline()
    doc = await pipeline.run("business_card.jpg")
    print(doc.full_text)
    print(f"Confidence: {doc.overall_confidence:.2%}")
"""

from byou.tools.ocr.ocr_result import (
    OCRBlock,
    OCRDocument,
    OCREngineInfo,
    OCRLine,
    OCRMetadata,
    OCRPoint,
    ConfidenceReport,
)
from byou.tools.ocr.ocr_provider import OCRProvider, ImageInput
from byou.tools.ocr.ocr_router import OCRRouter, OCRFailure, RouterConfig
from byou.tools.ocr.ocr_pipeline import OCRPipeline, ConfidenceEvaluator
from byou.tools.ocr.paddle_provider import PaddleOCRProvider
from byou.tools.ocr.cnocr_provider import CnOCRProvider
from byou.tools.ocr.ocr_field_extractor import FieldExtractor, FieldCandidates


# ── 兼容旧接口 ──────────────────────────────

class OCRTool:
    """Extract text from business card images — 兼容旧接口。

    新代码请直接使用 OCRPipeline:
        from byou.tools.ocr import OCRPipeline
        pipeline = OCRPipeline()
        doc = await pipeline.run("card.jpg")
    """

    def __init__(self, language: str = "ch"):
        self.language = language
        self._pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            self._pipeline = OCRPipeline()
        return self._pipeline

    async def extract_text(self, image_path: str) -> str:
        try:
            doc = await self.pipeline.run(image_path)
            return doc.full_text
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("OCRTool.extract_text failed: %s", e)
            return ""


__all__ = [
    # 管线
    "OCRPipeline",
    "ConfidenceEvaluator",
    # 路由
    "OCRRouter",
    "OCRFailure",
    "RouterConfig",
    # 引擎
    "OCRProvider",
    "PaddleOCRProvider",
    "CnOCRProvider",
    # 字段提取
    "FieldExtractor",
    "FieldCandidates",
    "ImageInput",
    # 数据模型
    "OCRBlock",
    "OCRDocument",
    "OCREngineInfo",
    "OCRLine",
    "OCRMetadata",
    "OCRPoint",
    "ConfidenceReport",
]
