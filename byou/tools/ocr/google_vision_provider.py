"""Google Vision OCR Provider — 多语言名片识别（可选依赖）。

需要 GOOGLE_VISION_API_KEY 环境变量，未配置时自动禁用。
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from byou.config import settings
from byou.tools.ocr.ocr_provider import OCRProvider, ImageInput
from byou.tools.ocr.ocr_result import (
    OCRDocument,
    OCRBlock,
    OCREngineInfo,
    OCRMetadata,
    OCRPoint,
    OCRLine,
)

logger = logging.getLogger(__name__)

_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


class GoogleVisionProvider(OCRProvider):
    """Google Vision OCR — 60+ 语言高精度识别。"""

    def __init__(self) -> None:
        self._api_key = settings.google_vision_api_key
        self._enabled = bool(self._api_key)
        if not self._enabled:
            logger.debug("GoogleVisionProvider: no API key, disabled.")

    @property
    def engine_info(self) -> OCREngineInfo:
        return OCREngineInfo(
            name="google_vision",
            version="v1",
            languages=["*"],   # 60+ languages
            gpu_accelerated=False,
        )

    def is_available(self) -> bool:
        return self._enabled

    async def detect(self, image: ImageInput) -> list[OCRBlock]:
        result = await self._call_vision(image, ["TEXT_DETECTION"])
        return self._parse_blocks(result)

    async def recognize(
        self,
        image: ImageInput,
        blocks: list[OCRBlock] | None = None,
    ) -> OCRDocument:
        result = await self._call_vision(image, ["TEXT_DETECTION"])
        return self._parse_document(result)

    # ── Internal ────────────────────────────────────────────────

    async def _call_vision(self, image: ImageInput, features: list[str]) -> dict:
        if not self._enabled:
            return {}
        img_b64 = self._encode_image(image)
        payload = {
            "requests": [
                {
                    "image": {"content": img_b64},
                    "features": [{"type": ft} for ft in features],
                }
                for ft in features
            ]
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{_VISION_ENDPOINT}?key={self._api_key}",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("Google Vision error: %s", e)
            return {}

    def _encode_image(self, image: ImageInput) -> str:
        if isinstance(image, bytes):
            return base64.b64encode(image).decode("utf-8")
        with open(Path(image), "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _parse_blocks(self, api_result: dict) -> list[OCRBlock]:
        blocks: list[OCRBlock] = []
        responses = api_result.get("responses", [])
        if not responses:
            return blocks
        annotations = responses[0].get("textAnnotations", [])
        if not annotations:
            return blocks

        # annotations[0] = full text; rest = individual words with boundingPoly
        for ann in annotations[1:]:
            vertices = ann.get("boundingPoly", {}).get("vertices", [])
            if len(vertices) >= 4:
                bbox = [
                    OCRPoint(x=v.get("x", 0), y=v.get("y", 0))
                    for v in vertices[:4]
                ]
                line = OCRLine(
                    text=ann.get("description", ""),
                    confidence=ann.get("confidence", 0.0),
                    bbox=bbox,
                )
                block = OCRBlock(
                    block_type="text",
                    lines=[line],
                    bbox=bbox,
                )
                blocks.append(block)

        return blocks

    def _parse_document(self, api_result: dict) -> OCRDocument:
        responses = api_result.get("responses", [])
        if not responses:
            return OCRDocument(
                full_text="",
                engine_name=self.engine_info.name,
                engine_info=self.engine_info,
                warnings=["No response from Google Vision API"],
            )

        annotations = responses[0].get("textAnnotations", [])
        full_text = annotations[0].get("description", "") if annotations else ""
        blocks = self._parse_blocks(api_result)

        confs = [l.confidence for b in blocks for l in b.lines]
        avg_conf = sum(confs) / len(confs) if confs else 0.0

        return OCRDocument(
            full_text=full_text,
            blocks=blocks,
            engine_name=self.engine_info.name,
            engine_info=self.engine_info,
            overall_confidence=round(avg_conf, 4),
            metadata=OCRMetadata(engine=self.engine_info.name),
        )
