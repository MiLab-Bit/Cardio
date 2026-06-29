"""OCR Tool — image text extraction via Tesseract or LLM Vision."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from byou.core.llm_client import get_client

logger = logging.getLogger(__name__)


class OCRTool:
    """Extract text from business card images."""

    def __init__(self, language: str = "chi_sim+eng"):
        self.language = language
        self._tesseract_ok = self._check_tesseract()

    @staticmethod
    def _check_tesseract() -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            logger.warning("Tesseract unavailable, will fall back to LLM Vision OCR")
            return False

    async def extract_text(self, image_path: str) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        if self._tesseract_ok:
            return await self._tesseract_ocr(path)

        return await self._llm_vision_ocr(path)

    async def _tesseract_ocr(self, path: Path) -> str:
        import pytesseract
        from PIL import Image

        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang=self.language)
        logger.info("Tesseract OCR: %d chars", len(text))
        return text.strip()

    async def _llm_vision_ocr(self, path: Path) -> str:
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        ext = path.suffix.lower().replace(".", "")
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "tiff": "tiff", "tif": "tiff"}
        mime = mime_map.get(ext, "jpeg")

        client = get_client()
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all text from this business card/image. Preserve the original formatting."},
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                ],
            }],
        )
        text = resp.choices[0].message.content or ""
        logger.info("LLM Vision OCR: %d chars", len(text))
        return text.strip()
