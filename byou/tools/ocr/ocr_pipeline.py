"""OCR 执行管线 — 预处理 → 路由 → 置信度评估 → 输出。

每一步的输入/输出:
1. preprocess:   image bytes → enhanced image
2. route:        enhanced image → OCRDocument (自动选引擎+fallback)
3. evaluate:     OCRDocument → ConfidenceReport
4. output:       OCRDocument → 返回 (含置信度报告)
"""

from __future__ import annotations

import logging

from byou.tools.ocr.ocr_provider import ImageInput
from byou.tools.ocr.ocr_result import (
    ConfidenceReport,
    OCRDocument,
)
from byou.tools.ocr.ocr_router import OCRRouter

logger = logging.getLogger(__name__)


class ConfidenceEvaluator:
    """置信度评估器 — 分析 OCRDocument 的质量并生成建议。"""

    def __init__(self, threshold: float = 0.85, line_threshold: float = 0.7):
        self.threshold = threshold
        self.line_threshold = line_threshold

    def evaluate(self, doc: OCRDocument) -> ConfidenceReport:
        """评估 OCRDocument 的置信度。

        Args:
            doc: OCR 输出文档

        Returns:
            ConfidenceReport (suggestion ∈ {pass, fallback, manual_review})
        """
        per_block: dict[int, float] = {}
        per_line: dict[str, float] = {}
        low_blocks: list[int] = []
        low_lines: list[str] = []

        for block in doc.blocks:
            bid = block.block_id
            per_block[bid] = block.avg_confidence
            if block.avg_confidence < self.threshold:
                low_blocks.append(bid)

            for line in block.lines:
                key = line.text[:20] if len(line.text) > 20 else line.text
                per_line[key] = line.confidence
                if line.is_low_confidence(self.line_threshold):
                    low_lines.append(line.text)

        # 建议
        if doc.overall_confidence >= self.threshold:
            suggestion = "pass"
        elif doc.overall_confidence >= 0.6:
            suggestion = "fallback"
        else:
            suggestion = "manual_review"

        return ConfidenceReport(
            overall=doc.overall_confidence,
            per_block=per_block,
            per_line=per_line,
            low_confidence_blocks=low_blocks,
            low_confidence_lines=low_lines,
            suggestion=suggestion,
        )


class OCRPipeline:
    """完整 OCR 管线 — Byou 的 OCR 子系统统一入口。

    封装了 Router + ConfidenceEvaluator，
    对上提供单一 run() 接口。

    Usage:
        pipeline = OCRPipeline()
        doc = await pipeline.run("card.jpg")
        print(f"Text: {doc.full_text}")
        print(f"Confidence: {doc.overall_confidence}")
        print(f"Reliable: {doc.is_reliable}")
    """

    def __init__(
        self,
        router: OCRRouter | None = None,
        evaluator: ConfidenceEvaluator | None = None,
    ):
        self.router = router or OCRRouter()
        self.evaluator = evaluator or ConfidenceEvaluator()

    async def run(self, image: ImageInput) -> OCRDocument:
        """执行完整 OCR 管线。

        Step 1-3: 路由 → OCR (含自动降级)
        Step 4:   置信度评估
        Step 5:   行级 fallback (如果部分行低置信)
        Step 6:   返回完整 OCRDocument
        """
        # Step 1-3: OCR (Router 内部处理检测→识别→fallback)
        doc = await self.router.execute(image)

        # Step 4: 置信度评估
        doc.confidence_report = self.evaluator.evaluate(doc)

        # Step 5: 行级 fallback (如果有部分行低置信)
        if doc.confidence_report.suggestion == "fallback":
            doc = await self.router.fallback_low_confidence_lines(doc, image)
            # 重新评估
            doc.confidence_report = self.evaluator.evaluate(doc)

        # Step 6: 返回
        logger.info(
            "OCR pipeline done: confidence=%.2f suggestion=%s fallback_level=%d",
            doc.overall_confidence,
            doc.confidence_report.suggestion,
            doc.fallback_level,
        )
        return doc
