"""OCR 名片字段提取器 v2 — 多语言增强版。

支持: 中文 | 英文 | 日文 | 韩文 | 国际电话号码
零 LLM 调用，纯正则 + 启发式。

修复: 电话正则全部重写，确保能实际匹配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from byou.tools.ocr.ocr_result import OCRDocument, OCRLine


@dataclass
class FieldCandidates:
    """名片字段候选结果 — 规则层输出"""

    # 正则可靠字段 (直接判定)
    phone: str = ""
    phones: list[str] = field(default_factory=list)
    email: str = ""
    emails: list[str] = field(default_factory=list)
    website: str = ""
    websites: list[str] = field(default_factory=list)
    wechat: str = ""
    linkedin: str = ""
    whatsapp: str = ""
    telegram: str = ""

    # 位置启发字段 (候选，待 LLM 确认)
    name_candidate: str = ""
    name_language: str = ""
    title_candidates: list[str] = field(default_factory=list)
    company_candidates: list[str] = field(default_factory=list)

    # 地址 (多语言)
    address_candidates: list[str] = field(default_factory=list)
    address_country: str = ""

    # OCR 元信息
    all_text: str = ""
    ocr_confidence: float = 0.0
    low_confidence_lines: list[str] = field(default_factory=list)
    engine_name: str = ""

    @property
    def has_confident_fields(self) -> bool:
        return bool(self.phone or self.email or self.website or self.wechat or self.linkedin)

    def to_llm_prompt_dict(self) -> dict[str, Any]:
        confident: dict[str, str] = {}
        if self.phone:
            confident["phone"] = self.phone
        if self.email:
            confident["email"] = self.email
        if self.website:
            confident["website"] = self.website
        if self.wechat:
            confident["wechat"] = self.wechat
        if self.linkedin:
            confident["linkedin"] = self.linkedin
        if self.whatsapp:
            confident["whatsapp"] = self.whatsapp

        return {
            "already_confirmed": confident,
            "name_candidate": self.name_candidate,
            "name_language": self.name_language,
            "title_candidates": self.title_candidates,
            "company_candidates": self.company_candidates,
            "address_candidates": self.address_candidates,
            "address_country": self.address_country,
            "full_ocr_text": self.all_text,
            "low_confidence_lines": self.low_confidence_lines,
            "ocr_confidence": self.ocr_confidence,
        }


class FieldExtractor:
    """多语言名片字段提取器。"""

    # ── 电话正则（修复版）─────────────────────────────
    # 中国大陆手机号: 1[3-9] + 9位 = 11位
    PHONE_CN = re.compile(r"(?:\+?86)?1[3-9]\d{9}")

    # 座机: 区号-号码
    PHONE_LANDLINE_CN = re.compile(r"(?:0\d{2,3}[-\－]\s?)?\d{7,8}(?:[-\－]\d{1,6})?")

    # 香港 +852
    PHONE_HK = re.compile(r"\+?852\d{8}")
    # 台湾 +886
    PHONE_TW = re.compile(r"\+?886\d{8,9}")
    # 美国/加拿大 +1
    PHONE_NA = re.compile(r"\+?1\d{10}")
    # 英国 +44
    PHONE_UK = re.compile(r"\+?44\d{9,10}")
    # 日本 +81
    PHONE_JP = re.compile(r"\+?81\d{9,10}")
    # 韩国 +82
    PHONE_KR = re.compile(r"\+?82\d{8,9}")
    # 新加坡 +65
    PHONE_SG = re.compile(r"\+?65\d{8}")
    # 印度 +91
    PHONE_IN = re.compile(r"\+?91[6-9]\d{9}")
    # 澳大利亚 +61
    PHONE_AU = re.compile(r"\+?61\d{9}")
    # 通用国际: +国家码+号码 (E.164 风格)
    PHONE_INTL = re.compile(r"\+[1-9]\d{7,14}")

    # ── 邮箱 ──────────────────────────────────────
    EMAIL = re.compile(r"[a-zA-Z0-9][\w.+-]*@[a-zA-Z0-9][\w.-]*\.[a-zA-Z]{2,}")

    # ── 网址 ──────────────────────────────────────
    URL = re.compile(
        r"https?://(?:www\.)?[a-zA-Z0-9][-\w.]*\.[a-zA-Z]{2,}(?:/[^\s]*)?"
        r"|www\.[a-zA-Z0-9][-\w.]*\.[a-zA-Z]{2,}(?:/[^\s]*)?"
    )

    # ── LinkedIn ───────────────────────────────────
    LINKEDIN_URL = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_%]+")
    LINKEDIN_HANDLE = re.compile(r"linkedin\.com/in/([a-zA-Z0-9\-_%]+)", re.IGNORECASE)

    # ── WhatsApp ──────────────────────────────────
    WHATSAPP_LINK = re.compile(r"https?://(?:wa\.me|api\.whatsapp\.com)/(\+?\d+)")
    WHATSAPP_TEXT = re.compile(r"(?:whatsapp|WhatsApp)[:\s]*(?:\+?[\d\s\-]+)", re.IGNORECASE)

    # ── Telegram ──────────────────────────────────
    TELEGRAM = re.compile(r"(?:telegram|Telegram|TG)[:\s]*@?([a-zA-Z0-9_]{5,32})", re.IGNORECASE)

    # ── 微信号 ──────────────────────────────────────
    WECHAT = re.compile(r"(?:微信|WeChat|wechat|VX|vx)[:：]?\s*([a-zA-Z][\w_-]{5,19})", re.IGNORECASE)

    # ── 职位关键词 ──────────────────────────────────
    TITLE_KEYWORDS = [
        "CEO", "CTO", "CFO", "COO", "CMO", "CIO", "CRO",
        "董事长", "副董事长", "执行董事", "独立董事",
        "总裁", "副总裁", "助理总裁",
        "总经理", "副总经理", "总经理助理",
        "总监", "副总监", "高级总监", "执行总监",
        "技术总监", "市场总监", "销售总监", "运营总监", "财务总监", "人力总监",
        "VP", "SVP", "EVP", "Director", "Senior Director",
        "经理", "副经理", "主管",
        "Manager", "Senior Manager",
        "工程师", "Engineer", "架构师", "Architect",
        "设计师", "Designer", "分析师", "Analyst",
        "顾问", "Consultant", "合伙人", "Partner",
        "代表", "Representative", "专员", "Specialist",
        "代表取締役", "取締役", "社長", "副社長", "部長", "課長", "係長",
    ]

    COMPANY_SUFFIXES = [
        "有限公司", "股份有限公司", "集团",
        "科技", "技术", "信息", "咨询", "服务", "贸易", "实业",
        "株式会社", "合同会社",
        "주식회사", "유한회사",
        "Inc.", "LLC", "Ltd.", "Corp.", "Corporation",
        "GmbH", "S.A.", "B.V.", "Pty", "Co.", "LP",
        "Sdn Bhd", "Berhad",
    ]

    NOT_NAME = re.compile(
        r"有限公司|股份|集团|科技|技术|信息|咨询|服务|贸易|实业|"
        r"株式会社|合同会社|주식회사|"
        r"Inc\.|LLC|Ltd\.|Corp\.|GmbH|"
        r"手机|电话|邮箱|传真|地址|网址|官网|邮编|微信|QQ|"
        r"扫一扫|二维码|关注|公众号|小程序|"
        r"LinkedIn|WhatsApp|Telegram|"
        r"Floor|Room|Suite|Bldg|Building|Road|Street|Ave|Blvd"
    )

    # ── 主提取方法 ──────────────────────────────────────────

    def extract(self, doc: OCRDocument) -> FieldCandidates:
        result = FieldCandidates()
        result.ocr_confidence = doc.overall_confidence
        result.engine_name = doc.engine_name

        lines = sorted(doc.lines, key=lambda l: (l.center_y, l.center_x))
        result.all_text = "\n".join(l.text for l in lines)

        result.low_confidence_lines = [
            l.text for l in lines if l.is_low_confidence(0.7)
        ]

        self._extract_regex_fields(result, lines)
        self._extract_heuristic_fields(result, lines)

        return result

    # ── Layer 1 实现 ──────────────────────────────────────

    def _extract_regex_fields(self, result: FieldCandidates, lines: list[OCRLine]) -> None:
        all_text = "\n".join(l.text for l in lines)

        # ── 电话 ──────────────────────────────────────
        for pattern in [
            self.PHONE_CN, self.PHONE_HK, self.PHONE_TW,
            self.PHONE_NA, self.PHONE_UK, self.PHONE_JP, self.PHONE_KR,
            self.PHONE_SG, self.PHONE_IN, self.PHONE_AU,
        ]:
            for m in pattern.finditer(all_text):
                phone = re.sub(r"[\s\-＋+()（）]", "", m.group())
                if phone and phone not in result.phones:
                    result.phones.append(phone)

        if not result.phones:
            for m in self.PHONE_INTL.finditer(all_text):
                phone = re.sub(r"[\s\-＋+()（）]", "", m.group())
                if phone and phone not in result.phones:
                    result.phones.append(phone)

        if result.phones:
            result.phone = result.phones[0]

        # ── 邮箱 ──────────────────────────────────────
        for m in self.EMAIL.finditer(all_text):
            email = m.group().lower()
            if email not in result.emails:
                result.emails.append(email)
        if result.emails:
            result.email = result.emails[0]

        # ── 网址 ──────────────────────────────────────
        for m in self.URL.finditer(all_text):
            url = m.group().strip()
            if url not in result.websites:
                result.websites.append(url)
        if result.websites:
            result.website = result.websites[0]

        # ── LinkedIn ───────────────────────────────────
        for m in self.LINKEDIN_URL.finditer(all_text):
            result.linkedin = m.group().strip()
            break
        if not result.linkedin:
            for m in self.LINKEDIN_HANDLE.finditer(all_text):
                handle = m.group(1)
                if handle:
                    result.linkedin = f"https://linkedin.com/in/{handle}"
                    break

        # ── WhatsApp ──────────────────────────────────
        for m in self.WHATSAPP_LINK.finditer(all_text):
            result.whatsapp = m.group(1)
            break

        # ── Telegram ──────────────────────────────────
        for m in self.TELEGRAM.finditer(all_text):
            handle = m.group(1)
            if handle:
                result.telegram = f"@{handle}"
                break

        # ── 微信 ──────────────────────────────────────
        for m in self.WECHAT.finditer(all_text):
            result.wechat = m.group(1)
            break

    def _extract_heuristic_fields(self, result: FieldCandidates, lines: list[OCRLine]) -> None:
        sorted_lines = sorted(lines, key=lambda l: (l.center_y, l.center_x))

        # ── 姓名检测 (多语言) ────────────────────────
        for line in sorted_lines:
            text = line.text.strip()
            if not text or len(text) > 30:
                continue
            if self._looks_like_name_zh(text):
                result.name_candidate = text
                result.name_language = "zh"
                break
            if self._looks_like_name_en(text):
                result.name_candidate = text
                result.name_language = "en"
                break
            if self._looks_like_name_ja(text):
                result.name_candidate = text
                result.name_language = "ja"
                break
            if self._looks_like_name_ko(text):
                result.name_candidate = text
                result.name_language = "ko"
                break

        # ── 职位 ──────────────────────────────────────
        for line in sorted_lines:
            text = line.text.strip()
            if any(kw in text for kw in self.TITLE_KEYWORDS) and len(text) <= 40:
                result.title_candidates.append(text)

        # ── 公司名 ────────────────────────────────────
        for line in sorted_lines:
            text = line.text.strip()
            if (any(s in text for s in self.COMPANY_SUFFIXES)
                    and text != result.name_candidate
                    and len(text) >= 4):
                result.company_candidates.append(text)

        # ── 地址 ──────────────────────────────────────
        result.address_candidates = self._extract_addresses(sorted_lines)

    # ── 姓名检测辅助 ──────────────────────────────

    @staticmethod
    def _looks_like_name_zh(text: str) -> bool:
        clean = re.sub(r"(先生|女士|小姐|老师|总$|董$)", "", text)
        chinese = sum(1 for c in clean if "\u4e00" <= c <= "\u9fff")
        return 2 <= len(clean) <= 4 and chinese == len(clean)

    @staticmethod
    def _looks_like_name_en(text: str) -> bool:
        words = text.split()
        if not (2 <= len(words) <= 4):
            return False
        if not all(w[0].isupper() for w in words if w):
            return False
        if any(kw.lower() in text.lower() for kw in FieldExtractor.TITLE_KEYWORDS):
            return False
        if any(s in text for s in FieldExtractor.COMPANY_SUFFIXES):
            return False
        return True

    @staticmethod
    def _looks_like_name_ja(text: str) -> bool:
        if not text or len(text) > 10:
            return False
        kanji = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        kana = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
        if kanji + kana < 2:
            return False
        if any(kw in text for kw in FieldExtractor.TITLE_KEYWORDS):
            return False
        return True

    @staticmethod
    def _looks_like_name_ko(text: str) -> bool:
        if not text or len(text) > 8:
            return False
        hangul = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
        if hangul < 2:
            return False
        if any(kw.lower() in text.lower() for kw in ["inc", "ltd", "corp"]):
            return False
        return True

    # ── 地址提取 ──────────────────────────────────────

    def _extract_addresses(self, lines: list[OCRLine]) -> list[str]:
        candidates = []
        addr_keywords = [
            "路", "街", "大道", "巷", "号", "楼", "室", "层", "广场", "大厦",
            "省", "市", "区", "县", "镇",
            "Street", "St.", "Road", "Rd.", "Avenue", "Ave.", "Boulevard", "Blvd",
            "Floor", "Fl.", "Room", "Suite", "Building", "Bldg", "Tower",
            "#", "-",
            "丁目", "番地", "号室", "階", "棟",
        ]
        for line in lines:
            text = line.text.strip()
            if any(kw in text for kw in addr_keywords) and 5 < len(text) < 100:
                candidates.append(text)
        return candidates[:3]

    # ── 辅助 ──────────────────────────────────────

    @staticmethod
    def _is_company_suffix(text: str) -> bool:
        return any(s in text for s in FieldExtractor.COMPANY_SUFFIXES) and len(text) >= 4
