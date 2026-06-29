# tests/intake/test_card_adapter.py
"""Card adapter + normalizer tests — PaddleOCR → BusinessCard."""

import pytest

from byou.intake.card.adapter import CardAdapter
from byou.intake.card.normalizer import CardFieldNormalizer
from byou.intake.models import BusinessCard


# ══════════════════════════════════════════════════════════
# Field Normalizer
# ══════════════════════════════════════════════════════════

class TestFieldNormalizer:
    def test_normalize_name_chinese(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"name": "张三"})
        assert result["name"] == "张三"

    def test_normalize_name_with_prefix(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"name": "姓名:张三 先生"})
        assert "张三" in result["name"]

    def test_phone_strip_prefix(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"phone": "+86 138-0013-8000"})
        assert result["phone"] == "13800138000"

    def test_phone_keep_digits_only(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"phone": "86-13800138000"})
        assert result["phone"] == "13800138000"

    def test_email_lowercase(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"email": "ZhangSan@Tencent.COM"})
        assert result["email"] == "zhangsan@tencent.com"

    def test_industry_inference(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"company": "腾讯科技", "industry_hint": ""})
        assert result["industry_hint"] == "信息技术"

    def test_industry_existing_not_overwritten(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"company": "腾讯科技", "industry_hint": "互联网"})
        assert result["industry_hint"] == "互联网"

    def test_whitespace_collapse(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({"title": "  技术  总监  "})
        assert result["title"] == "技术 总监"

    def test_empty_input(self):
        norm = CardFieldNormalizer()
        result = norm.normalize({})
        assert result["name"] == ""
        assert result["company"] == ""
        assert result["ocr_confidence"] == 0.0


# ══════════════════════════════════════════════════════════
# CardAdapter
# ══════════════════════════════════════════════════════════

class TestCardAdapterPreparsed:
    def test_from_preparsed_full(self):
        adapter = CardAdapter()
        card = adapter.from_preparsed({
            "name": "张三",
            "company": "腾讯科技",
            "title": "技术总监",
            "phone": "+86 13800138000",
            "email": "zhangsan@tencent.com",
            "ocr_confidence": 0.92,
        })
        assert isinstance(card, BusinessCard)
        assert card.name == "张三"
        assert card.company == "腾讯科技"
        assert card.phone == "13800138000"  # normalized

    def test_process_detects_preparsed(self):
        adapter = CardAdapter()
        card = adapter.process({"name": "李四", "company": "阿里"})
        assert card.name == "李四"

    def test_process_batch(self):
        adapter = CardAdapter()
        cards = adapter.process_batch([
            {"name": "张三"},
            {"name": "李四"},
        ])
        assert len(cards) == 2
        assert cards[1].name == "李四"

    def test_empty_input_not_crash(self):
        adapter = CardAdapter()
        card = adapter.process({})
        assert isinstance(card, BusinessCard)
        assert card.name == ""


# ══════════════════════════════════════════════════════════
# CardAdapter — Raw line parsing
# ══════════════════════════════════════════════════════════

class TestCardAdapterRawLines:
    def test_parse_paddleocr_lines(self):
        """Simulated PaddleOCR output: [[bbox, (text, conf)], ...]"""
        raw = {
            "lines": [
                [[[10, 10], [100, 10], [100, 30], [10, 30]], ("张三", 0.95)],
                [[[10, 40], [200, 40], [200, 60], [10, 60]], ("腾讯科技有限公司", 0.92)],
                [[[10, 70], [150, 70], [150, 90], [10, 90]], ("技术总监", 0.88)],
                [[[10, 100], [180, 100], [180, 120], [10, 120]], ("zhangsan@tencent.com", 0.99)],
                [[[10, 130], [160, 130], [160, 150], [10, 150]], ("13800138000", 0.97)],
            ]
        }
        adapter = CardAdapter()
        card = adapter.process(raw)
        assert card.name == "张三"
        assert "腾讯" in card.company
        assert card.email == "zhangsan@tencent.com"
        assert "13800138000" in card.phone
        assert card.ocr_confidence > 0.9

    def test_parse_text_lines(self):
        """Input with text_lines instead of PaddleOCR format."""
        raw = {
            "text_lines": [
                {"text": "李四", "confidence": 0.96},
                {"text": "阿里巴巴集团", "confidence": 0.93},
                {"text": "lisi@alibaba.com", "confidence": 0.99},
            ]
        }
        adapter = CardAdapter()
        card = adapter.process(raw)
        assert card.name == "李四"
        assert "阿里" in card.company
        assert card.email == "lisi@alibaba.com"

    def test_raw_text_fallback(self):
        """When input is plain string, it goes to raw_text."""
        adapter = CardAdapter()
        card = adapter.process("some plain text")
        assert isinstance(card, BusinessCard)
        assert card.raw_text  # raw text captured
