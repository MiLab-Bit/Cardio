# byou/intake/card/adapter.py
"""Card adapter — PaddleOCR raw output → BusinessCard.

Handles two input modes:
  1. Pre-parsed dict (already field-extracted by NER) — direct normalize
  2. Raw PaddleOCR text lines — field detection → parse → normalize

Provider payload (PaddleOCR bbox/txt/confidence tuples) NEVER leaves this module.
Only BusinessCard exits to extraction layer.
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.card.normalizer import CardFieldNormalizer
from byou.intake.models import BusinessCard

logger = logging.getLogger(__name__)


class CardAdapter:
    """Convert OCR provider output → BusinessCard.

    Usage:
        adapter = CardAdapter()
        card = adapter.process(raw_paddleocr_result)
        # or
        card = adapter.from_preparsed(field_dict)

    Provider payload shape (PaddleOCR v2 typical):
        [[bbox, (text, confidence)], ...]
        → adapter._parse_lines() → field dict
        → normalizer.normalize() → clean dict
        → BusinessCard(...)
    """

    # Field detection patterns — used for raw line parsing
    _FIELD_PATTERNS: list[tuple[str, str]] = [
        ("email", r"^[\w.+-]+@[\w-]+\.[\w.-]+$"),
        ("phone", r"^[*+\d][\d\s\-()（）]{6,}$"),
        ("website", r"^(https?://)?[\w.-]+\.[a-z]{2,}(/[\w./-]*)?$"),
    ]

    def __init__(self):
        self._normalizer = CardFieldNormalizer()

    # ── Main entry ─────────────────────────────────────

    def process(self, raw: dict[str, Any]) -> BusinessCard:
        """Main entry: raw input → BusinessCard.

        If raw has 'name' key → treat as pre-parsed.
        If raw has 'lines' or 'text_lines' → try raw line parsing.
        """
        # Mode 1: pre-parsed dict (most common for P1)
        if "name" in raw or "company" in raw:
            return self.from_preparsed(raw)

        # Mode 2: raw text lines from OCR (PaddleOCR format)
        if "lines" in raw:
            parsed = self._parse_lines(raw["lines"])
            return self.from_preparsed(parsed)

        if "text_lines" in raw:
            parsed = self._parse_text_lines(raw["text_lines"])
            return self.from_preparsed(parsed)

        # Fallback: treat as raw text blob → store in raw_text only
        return self.from_preparsed({"raw_text": str(raw)})

    def from_preparsed(self, raw: dict[str, Any]) -> BusinessCard:
        """Create BusinessCard from pre-parsed field dict."""
        cleaned = self._normalizer.normalize(raw)
        return BusinessCard(**cleaned)

    def process_batch(self, raws: list[dict[str, Any]]) -> list[BusinessCard]:
        return [self.process(r) for r in raws]

    # ── Raw line parsing (PaddleOCR format) ─────────────

    def _parse_lines(self, lines: list) -> dict[str, Any]:
        """Parse PaddleOCR-style lines: [[bbox, (text, confidence)], ...].

        Returns pre-parsed field dict.
        """
        text_lines: list[dict[str, Any]] = []
        for line in lines:
            if isinstance(line, (list, tuple)) and len(line) >= 2:
                # PaddleOCR format: [bbox, (text, conf)]
                text_info = line[1] if isinstance(line[1], (list, tuple)) else (str(line[1]), 1.0)
                text_lines.append({
                    "text": str(text_info[0]),
                    "confidence": float(text_info[1]) if len(text_info) > 1 else 1.0,
                })
            elif isinstance(line, dict):
                text_lines.append(line)

        return self._parse_text_lines(text_lines)

    def _parse_text_lines(self, text_lines: list[dict[str, Any]]) -> dict[str, Any]:
        """Heuristic field detection from text lines.

        Strategy:
          - First line with Chinese name pattern → name
          - Line matching email pattern → email
          - Line matching phone pattern → phone
          - Remaining → company/title/address by position + content
        """
        import re
        result: dict[str, Any] = {
            "raw_text": "\n".join(t.get("text", "") for t in text_lines),
            "name": "", "company": "", "title": "", "phone": "",
            "email": "", "website": "", "address": "",
            "ocr_confidence": 0.0,
        }

        assigned: set[int] = set()
        confidences: list[float] = []

        # Pass 1: detect email and phone by pattern
        for i, line in enumerate(text_lines):
            text = line.get("text", "").strip()
            conf = float(line.get("confidence", 1.0))
            confidences.append(conf)

            for field, pattern in self._FIELD_PATTERNS:
                if re.match(pattern, text, re.IGNORECASE):
                    if not result[field]:
                        result[field] = text
                        assigned.add(i)
                    break

        # Pass 2: detect name (first 2-3 char Chinese)
        import re as _re
        for i, line in enumerate(text_lines):
            if i in assigned:
                continue
            text = line.get("text", "").strip()
            # Chinese name: 2-3 chars, no spaces
            if _re.match(r"^[\u4e00-\u9fff]{2,3}$", text):
                result["name"] = text
                assigned.add(i)
                break

        # Pass 3: remaining lines → company (longest), title, address
        remaining = [t for i, t in enumerate(text_lines) if i not in assigned]
        for line in remaining:
            text = line.get("text", "").strip()
            if not text:
                continue
            if not result["company"] and len(text) >= 4:
                result["company"] = text
            elif not result["title"]:
                result["title"] = text
            elif not result["address"]:
                result["address"] = text

        # Average confidence
        if confidences:
            result["ocr_confidence"] = sum(confidences) / len(confidences)

        return result
