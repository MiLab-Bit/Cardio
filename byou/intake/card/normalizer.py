# byou/intake/card/normalizer.py
"""Card field normalizer — cleans and standardizes OCR/NER output.

Knows about provider quirks (PaddleOCR, Tesseract) but only outputs
clean BusinessCard-compatible dicts.  Provider-specific logic STAYS HERE.
"""

from __future__ import annotations

import re
from typing import Any


class CardFieldNormalizer:
    """Normalize raw OCR/NER fields into clean BusinessCard-compatible dicts.

    Handles:
      - Chinese/English name format normalization
      - Phone number cleanup (+86, spaces, dashes)
      - Email lowercase + validation
      - Title/company whitespace cleanup
      - Industry hint inference from company name keywords
    """

    # Known phone prefixes to strip (China mainland)
    _PHONE_PREFIXES = ["+86", "86-", "0086"]

    # Industry keyword → hint mapping
    _INDUSTRY_HINTS: dict[str, str] = {
        "科技": "信息技术",
        "信息": "信息技术",
        "软件": "信息技术",
        "数据": "信息技术",
        "网络": "信息技术",
        "互联": "互联网",
        "电商": "电子商务",
        "电子": "电子商务",
        "医疗": "医疗健康",
        "医药": "医疗健康",
        "生物": "医疗健康",
        "金融": "金融服务",
        "银行": "金融服务",
        "证券": "金融服务",
        "保险": "金融服务",
        "投资": "金融服务",
        "教育": "教育培训",
        "培训": "教育培训",
        "学校": "教育培训",
        "制造": "制造业",
        "工业": "制造业",
        "汽车": "制造业",
        "新能源": "能源",
        "能源": "能源",
        "地产": "房地产",
        "房产": "房地产",
        "咨询": "专业服务",
        "服务": "专业服务",
        "贸易": "贸易零售",
        "零售": "贸易零售",
        "传媒": "文化传媒",
        "文化": "文化传媒",
        "广告": "文化传媒",
        "餐饮": "餐饮酒店",
        "酒店": "餐饮酒店",
        "旅游": "旅游出行",
        "出行": "旅游出行",
        "物流": "物流运输",
        "运输": "物流运输",
    }

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw extraction dict → clean dict for BusinessCard."""
        return {
            "raw_text": self._clean_text(raw.get("raw_text", "")),
            "name": self._normalize_name(raw.get("name", "")),
            "company": self._clean_text(raw.get("company", "")),
            "title": self._clean_text(raw.get("title", "")),
            "phone": self._normalize_phone(raw.get("phone", "")),
            "email": self._normalize_email(raw.get("email", "")),
            "website": self._clean_text(raw.get("website", "")),
            "address": self._clean_text(raw.get("address", "")),
            "industry_hint": self._infer_industry(
                raw.get("company", ""),
                raw.get("industry_hint", ""),
            ),
            "ocr_confidence": float(raw.get("ocr_confidence") or 0.0),
            "ner_confidence": float(raw.get("ner_confidence") or 0.0),
            "source_image_eid": str(raw.get("source_image_eid", "") or ""),
            "source_ocr_eid": str(raw.get("source_ocr_eid", "") or ""),
        }

    # ── Field normalizers ──────────────────────────────

    @staticmethod
    def _clean_text(text: Any) -> str:
        """Strip whitespace, collapse multiple spaces."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", str(text)).strip()

    @classmethod
    def _normalize_name(cls, name: Any) -> str:
        """Normalize person name — strip spaces, remove generic prefixes."""
        name = cls._clean_text(name)
        # Remove common non-name prefixes that OCR picks up
        for prefix in ["姓名:", "联系人:", "先生", "女士", "联系人", "Contact:"]:
            name = name.replace(prefix, "")
        return cls._clean_text(name)

    @classmethod
    def _normalize_phone(cls, phone: Any) -> str:
        """Normalize phone number to digits-only format."""
        phone = cls._clean_text(phone)
        # Remove known prefixes
        for prefix in cls._PHONE_PREFIXES:
            if phone.startswith(prefix):
                phone = phone[len(prefix):]
        # Keep only digits
        digits = re.sub(r"\D", "", phone)
        return digits

    @classmethod
    def _normalize_email(cls, email: Any) -> str:
        """Lowercase and trim email."""
        email = cls._clean_text(email)
        return email.lower()

    @classmethod
    def _infer_industry(cls, company: str, existing_hint: str) -> str:
        """Infer industry from company name keywords.

        Only applies if existing_hint is empty.
        """
        if existing_hint:
            return existing_hint

        for keyword, hint in cls._INDUSTRY_HINTS.items():
            if keyword in company:
                return hint

        return ""
