"""OCR Router — 自动选路 + fallback 编排。

选路逻辑:
1. 检测所有已注册引擎的可用性
2. 按优先级: PaddleOCR → CnOCR → (未来: TrOCR → LLM)
3. 主引擎执行 detect + recognize
4. 置信度 < 阈值 → 自动降级到下一引擎
5. 所有引擎失败 → 抛 OCRFailure
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from byou.tools.ocr.ocr_provider import OCRProvider, ImageInput
from byou.tools.ocr.ocr_result import OCRDocument
from byou.tools.ocr.paddle_provider import PaddleOCRProvider
from byou.tools.ocr.cnocr_provider import CnOCRProvider
from byou.tools.ocr.google_vision_provider import GoogleVisionProvider

logger = logging.getLogger(__name__)


@dataclass
class RouterConfig:
    """路由器配置"""
    confidence_threshold: float = 0.85          # 整体置信度阈值
    line_confidence_threshold: float = 0.7      # 单行置信度阈值（低于此值触发行级fallback）
    max_fallbacks: int = 3                      # 最大降级次数
    enable_auto_detect: bool = True             # 自动检测引擎可用性


class OCRFailure(Exception):
    """所有 OCR 引擎均失败。"""
    pass


class OCRRouter:
    """OCR 选路器 — 自动选择合适的引擎执行 OCR。

    Usage:
        router = OCRRouter()
        doc = await router.execute("card.jpg")
        if doc.is_reliable:
            print(doc.full_text)
        else:
            print(f"Low confidence: {doc.overall_confidence}")
    """

    def __init__(
        self,
        providers: list[OCRProvider] | None = None,
        config: RouterConfig | None = None,
    ):
        self.config = config or RouterConfig()
        self.providers = providers if providers is not None else self._default_providers()

        # 过滤掉不可用的引擎
        available = [p for p in self.providers if p.is_available()]
        if not available:
            logger.warning("No OCR providers available! OCR will fail for all inputs.")
        else:
            logger.info(
                "OCR Router initialized with %d providers: %s",
                len(available),
                ", ".join(p.engine_info.name for p in available),
            )

        self.providers = available

    # ── 主入口 ───────────────────────────────

    async def execute(self, image: ImageInput) -> OCRDocument:
        """执行 OCR 管线，自动降级。

        Args:
            image: 图片路径 / bytes / Path

        Returns:
            OCRDocument (可能包含 warnings 和 fallback 记录)

        Raises:
            OCRFailure: 所有引擎都失败
        """
        if not self.providers:
            raise OCRFailure("No OCR providers available")

        last_doc: OCRDocument | None = None
        errors: list[str] = []
        chain: list[str] = []

        max_tries = min(len(self.providers), self.config.max_fallbacks)

        for i, provider in enumerate(self.providers[:max_tries]):
            chain.append(provider.engine_info.name)
            try:
                doc = await provider.detect_and_recognize(image)
                doc.fallback_level = i
                doc.metadata.fallback_chain = chain

                if doc.overall_confidence >= self.config.confidence_threshold:
                    logger.info(
                        "OCR success: engine=%s confidence=%.2f level=%d",
                        provider.engine_info.name,
                        doc.overall_confidence,
                        i,
                    )
                    return doc

                # 低置信度 → 记录并继续
                logger.info(
                    "OCR low confidence: engine=%s confidence=%.2f (threshold=%.2f), trying fallback",
                    provider.engine_info.name,
                    doc.overall_confidence,
                    self.config.confidence_threshold,
                )
                last_doc = doc

            except Exception as e:
                msg = f"{provider.engine_info.name}: {type(e).__name__}: {e}"
                errors.append(msg)
                logger.warning("OCR engine failed: %s", msg)
                continue

        # 所有引擎都跑完了，返回最好的结果（或报错）
        if last_doc is not None:
            last_doc.warnings.append(
                f"Best confidence {last_doc.overall_confidence:.2f} below threshold "
                f"{self.config.confidence_threshold}. " 
                f"Chain: {' → '.join(chain)}"
            )
            if errors:
                last_doc.warnings.append(f"Errors: {'; '.join(errors[-2:])}")
            return last_doc

        raise OCRFailure(
            f"All {len(chain)} OCR engine(s) failed. " 
            f"Chain: {' → '.join(chain)}. " 
            f"Errors: {'; '.join(errors[-3:])}"
        )

    # ── 行级 fallback ─────────────────────────

    async def fallback_low_confidence_lines(
        self,
        doc: OCRDocument,
        image: ImageInput,
    ) -> OCRDocument:
        """对单个文档的低置信度行用备选引擎重识别。

        Args:
            doc: 主引擎输出
            image: 原始图片

        Returns:
            更新后的 OCRDocument（低置信行已被备选引擎结果替换）
        """
        low_lines = doc.get_low_confidence_lines(self.config.line_confidence_threshold)
        if not low_lines:
            return doc

        # 找到下一个可用引擎
        current_name = doc.engine_name
        backup = self._next_provider(current_name)
        if backup is None:
            doc.warnings.append(
                f"No fallback engine available for {len(low_lines)} low-confidence lines"
            )
            return doc

        try:
            backup_doc = await backup.detect_and_recognize(image)

            # 替换低置信度行
            replaced = 0
            for block in doc.blocks:
                for line in block.lines:
                    if line.is_low_confidence(self.config.line_confidence_threshold):
                        match = self._find_best_match(line, backup_doc.lines)
                        if match and match.confidence > line.confidence:
                            old_text = line.text
                            line.text = match.text
                            line.confidence = match.confidence
                            line.source_engine = f"{line.source_engine}→{backup.engine_info.name}"
                            replaced += 1
                            logger.debug(
                                "Fallback line: '%s' → '%s' (%.2f→%.2f)",
                                old_text, match.text, line.confidence, match.confidence,
                            )

            # 重新计算置信度
            self._recalc_doc_confidence(doc)
            doc.warnings.append(
                f"Line-level fallback: {replaced}/{len(low_lines)} lines improved by {backup.engine_info.name}"
            )

        except Exception as e:
            doc.warnings.append(f"Line fallback failed: {e}")

        return doc

    # ── 引擎管理 ─────────────────────────────

    @staticmethod
    def _default_providers() -> list[OCRProvider]:
        """按优先级返回默认引擎列表。

        Routing strategy:
        - Chinese/heavy CJK text: PaddleOCR → CnOCR
        - Multilingual (EN/JP/KR/etc.): Google Vision → PaddleOCR
        - Auto-detect based on OCR results quality
        """
        providers: list[OCRProvider] = []

        # 1. PaddleOCR (主力 — 中文+英文最强)
        pad = PaddleOCRProvider(lang="ch")
        providers.append(pad)

        # 2. CnOCR (中文备选 — PyTorch原生，轻量)
        cn = CnOCRProvider()
        providers.append(cn)

        # 3. Google Vision (多语言 — 60+ languages, 全球名片)
        gv = GoogleVisionProvider()
        providers.append(gv)

        return providers

    def _next_provider(self, current_name: str) -> OCRProvider | None:
        """找到当前引擎之后的下一个可用引擎。"""
        found = False
        for p in self.providers:
            if found and p.is_available():
                return p
            if p.engine_info.name == current_name:
                found = True
        return None

    # ── 工具 ─────────────────────────────────

    @staticmethod
    def _find_best_match(line, candidates: list) -> object | None:
        """在候选行中找与目标行空间位置最近的匹配。"""
        if not candidates:
            return None
        # 简单策略: 按 y 坐标最近匹配
        best = min(candidates, key=lambda c: abs(c.center_y - line.center_y))
        return best

    @staticmethod
    def _recalc_doc_confidence(doc: OCRDocument) -> None:
        all_confs: list[float] = []
        for block in doc.blocks:
            block.recalc_confidence()
            if block.lines:
                all_confs.extend(l.confidence for l in block.lines)
        doc.overall_confidence = (
            round(sum(all_confs) / len(all_confs), 4) if all_confs else 0.0
        )
