"""CnOCR Provider — 基于 CnOCR DTrOCR 的中文 fallback 引擎。

核心依赖: pip install cnocr
模型: densenet_lite_136-gru (8M 参数, 默认)

定位: PaddleOCR 的中文强化备选。检测能力弱于 PaddleOCR，
      但 PyTorch 原生安装更轻，适合做低置信度降级。
"""

from __future__ import annotations

import logging
import time

from byou.tools.ocr.ocr_provider import OCRProvider, ImageInput
from byou.tools.ocr.ocr_result import (
    OCRBlock,
    OCRDocument,
    OCREngineInfo,
    OCRLine,
    OCRMetadata,
    OCRPoint,
)

logger = logging.getLogger(__name__)


class CnOCRProvider(OCRProvider):
    """CnOCR DTrOCR 引擎 — 中文名片 fallback。

    Usage:
        provider = CnOCRProvider()
        if provider.is_available():
            doc = await provider.detect_and_recognize("card.jpg")
    """

    def __init__(
        self,
        model_name: str = "densenet_lite_136-gru",
        context: str = "cpu",
    ):
        self._model_name = model_name
        self._context = context
        self._ocr = None
        self._available: bool | None = None

    @property
    def engine_info(self) -> OCREngineInfo:
        return OCREngineInfo(
            name="CnOCR",
            version=f"DTrOCR-{self._model_name}",
            languages=["ch", "en", "mixed"],
            gpu_accelerated=(self._context == "gpu"),
        )

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from cnocr import CnOcr
            self._available = True
            return True
        except ImportError:
            logger.info("CnOCR not available (cnocr not installed)")
        except Exception as e:
            logger.info("CnOCR not available: %s", e)
        self._available = False
        return False

    async def detect(self, image: ImageInput) -> list[OCRBlock]:
        """CnOCR 自带检测功能 (基于连通域 + MSER)。

        注意: 检测能力弱于 PaddleOCR，无法精确框选自由文本区域。
              但名片场景（文字规整排列）够用。
        """
        if not self.is_available():
            return []

        ocr = self._lazy_init()
        img = self._resolve_path(image)

        t0 = time.perf_counter()
        results = await self._to_thread(ocr.ocr, img)
        t1 = time.perf_counter()
        logger.debug("CnOCR detect: %.0f ms", (t1 - t0) * 1000)

        return self._parse_results_to_blocks(results)

    async def recognize(
        self,
        image: ImageInput,
        blocks: list[OCRBlock] | None = None,
    ) -> OCRDocument:
        """识别 — CnOCR 是端到端模型，检测+识别合在一起做。"""
        if not self.is_available():
            return OCRDocument(
                warnings=["CnOCR not available"],
                engine_name=self.engine_info.name,
                engine_info=self.engine_info,
            )

        ocr = self._lazy_init()
        img = self._resolve_path(image)

        t0 = time.perf_counter()
        results = await self._to_thread(ocr.ocr, img)
        t1 = time.perf_counter()

        doc = self._parse_results_to_document(results)
        doc.metadata.total_time_ms = round((t1 - t0) * 1000, 1)
        doc.metadata.engine = self.engine_info.name
        doc.engine_name = self.engine_info.name
        doc.engine_info = self.engine_info
        doc.source_path = str(img) if isinstance(img, str) else ""

        self._recalc_confidence(doc)
        return doc

    # ── 解析 ─────────────────────────────────

    @staticmethod
    def _parse_results_to_blocks(results: list) -> list[OCRBlock]:
        """CnOCR 结果 → OCRBlock 列表。

        CnOCR 格式: [
            {"text": "文字", "score": 0.95, "position": [[x1,y1],...,[x4,y4]]},
            ...
        ]
        """
        blocks: list[OCRBlock] = []
        for idx, item in enumerate(results):
            text = str(item.get("text", ""))
            conf = float(item.get("score", 1.0))
            pos = item.get("position", [])

            bbox = [OCRPoint(x=float(p[0]), y=float(p[1])) for p in pos[:4]]

            line = OCRLine(
                text=text,
                confidence=round(conf, 4),
                bbox=bbox,
                language="ch" if any('\u4e00' <= c <= '\u9fff' for c in text) else "en",
                source_engine="CnOCR",
            )

            block = OCRBlock(
                block_id=idx,
                block_type="text",
                lines=[line],
                bbox=bbox,
                avg_confidence=conf,
            )
            blocks.append(block)

        blocks.sort(key=lambda b: (b.center_y, b.center_x))
        return blocks

    @classmethod
    def _parse_results_to_document(cls, results: list) -> OCRDocument:
        blocks = cls._parse_results_to_blocks(results)
        all_text = [line.text for block in blocks for line in block.lines]
        return OCRDocument(
            full_text="\n".join(all_text),
            blocks=blocks,
        )

    @staticmethod
    def _recalc_confidence(doc: OCRDocument) -> None:
        all_confs: list[float] = []
        for block in doc.blocks:
            block.recalc_confidence()
            if block.lines:
                all_confs.extend(l.confidence for l in block.lines)
        doc.overall_confidence = (
            round(sum(all_confs) / len(all_confs), 4) if all_confs else 0.0
        )

    # ── 懒加载 ───────────────────────────────

    def _lazy_init(self):
        if self._ocr is not None:
            return self._ocr

        from cnocr import CnOcr

        self._ocr = CnOcr(
            model_name=self._model_name,
            context=self._context,
        )
        logger.info("CnOCR DTrOCR initialized (model=%s)", self._model_name)
        return self._ocr
