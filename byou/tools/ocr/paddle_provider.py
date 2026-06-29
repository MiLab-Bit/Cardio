"""PaddleOCR Provider — 基于 PP-OCRv4 的主力 OCR 引擎 (v3.x API)。

核心依赖: pip install paddleocr paddlepaddle
模型: PP-OCRv4 (DB 文本检测 + SVTR_LCNet 文字识别 + 方向分类器)

注意: PaddleOCR v3.x 内部使用 paddlex 引擎，需要 paddlepaddle 运行时。
      paddlepaddle 约 300MB+ CPU 版, GPU 版约 500MB+.
      如未安装 paddlepaddle，is_available() 返回 False，自动降级到 CnOCR。
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


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR PP-OCRv4 引擎。

    自动检测 paddlepaddle 是否已安装。
    未安装时降级到 CnOCR。
    """

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
    ):
        self._lang = lang
        self._use_gpu = use_gpu
        self._ocr = None
        self._available: bool | None = None  # tri-state: None=未检测

    @property
    def engine_info(self) -> OCREngineInfo:
        return OCREngineInfo(
            name="PaddleOCR",
            version="PP-OCRv4",
            languages=["ch", "en", "japan", "korean", "french", "german",
                       "italian", "spanish", "portuguese", "russian", "arabic"],
            gpu_accelerated=self._use_gpu,
        )

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            # PaddleOCR v3.x → 需要 paddlepaddle 运行时
            from paddleocr import PaddleOCR
            # 尝试初始化确认 paddlepaddle 可用
            PaddleOCR(lang=self._lang)
            self._available = True
            return True
        except RuntimeError as e:
            logger.info("PaddleOCR not available: %s", e)
        except ImportError:
            logger.info("PaddleOCR not available (paddleocr not installed)")
        except Exception as e:
            logger.info("PaddleOCR not available: %s", e)
        self._available = False
        return False

    async def detect(self, image: ImageInput) -> list[OCRBlock]:
        if not self.is_available():
            return []
        ocr = self._lazy_init()
        img = self._resolve_path(image)
        t0 = time.perf_counter()
        # PaddleOCR v3 API: ocr.ocr(img) → 全量检测+识别
        results = await self._to_thread(ocr.ocr, img)
        t1 = time.perf_counter()
        logger.debug("PaddleOCR detect: %.0f ms", (t1 - t0) * 1000)
        return self._parse_results_to_blocks(results)

    async def recognize(
        self,
        image: ImageInput,
        blocks: list[OCRBlock] | None = None,
    ) -> OCRDocument:
        if not self.is_available():
            return OCRDocument(
                warnings=["PaddleOCR not available"],
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

    # ── 解析 (v3.x API 输出格式) ────────────

    def _parse_results_to_blocks(self, results: list) -> list[OCRBlock]:
        """PaddleOCR v3 输出 → OCRBlock 列表。

        格式: [[bbox, text_info], ...]
        或者: [[[bbox, ...], ...]]  外层就是全部分组
        """
        blocks: list[OCRBlock] = []
        if not results:
            return blocks

        # 处理外层列表包裹
        data = results
        if len(results) == 1 and isinstance(results[0], list):
            data = results[0]

        for idx, item in enumerate(data):
            if not item or len(item) < 2:
                continue
            bbox_raw = item[0]
            text_raw = item[1]

            # 解析 bbox
            if isinstance(bbox_raw, list) and len(bbox_raw) >= 4:
                bbox = [OCRPoint(x=float(p[0]), y=float(p[1])) for p in bbox_raw[:4]]
            else:
                bbox = []

            # 解析 text + confidence
            if isinstance(text_raw, (list, tuple)) and len(text_raw) >= 2:
                text = str(text_raw[0])
                conf = round(float(text_raw[1]), 4)
            else:
                text = str(text_raw)
                conf = 1.0

            line = OCRLine(
                text=text,
                confidence=conf,
                bbox=bbox,
                language=self._classify_lang(text),
                source_engine=self.engine_info.name,
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

    def _parse_results_to_document(self, results: list) -> OCRDocument:
        blocks = self._parse_results_to_blocks(results)
        all_text = [line.text for block in blocks for line in block.lines]
        return OCRDocument(full_text="\n".join(all_text), blocks=blocks)

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

    @staticmethod
    def _classify_lang(text: str) -> str:
        if not text.strip():
            return "unknown"
        has_cjk = any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in text)
        has_alpha = any(c.isascii() and c.isalpha() for c in text)
        if has_cjk and has_alpha:
            return "mixed"
        if has_cjk:
            return "ch"
        if has_alpha:
            return "en"
        return "unknown"

    # ── 懒加载 ───────────────────────────────

    def _lazy_init(self):
        if self._ocr is not None:
            return self._ocr
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(lang=self._lang)
        logger.info("PaddleOCR PP-OCRv4 initialized (lang=%s)", self._lang)
        return self._ocr
