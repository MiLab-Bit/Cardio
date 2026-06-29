"""SLM Extractor — 字段抽取器。

设计:
- 标签驱动: 你传一个 labels 列表, 它从文本中抽取对应字段
- 支持中文公司名、人名、职位、联系方式等
- Heuristic fallback: 正则 + 模式匹配
"""

from __future__ import annotations

import re
import time
from typing import Any

from .types import (
    ExtractData,
    ExtractResult,
    ExtractedField,
    SLMCapability,
)

# ── 内置字段模式 ──────────────────────────────────────────────

_FIELD_PATTERNS: dict[str, str] = {
    "company_name": r'(?:公司|有限|集团|科技|技术|股份|合伙).{0,20}(?:有限(?:责任)?公司|股份(?:有限)?公司|集团有限公司|科技有限公司|技术有限公司|有限公司|集团|工作室|事务所)|(?:腾讯|阿里|百度|字节|华为|京东|美团|网易|小米|美团|滴滴|比亚迪|宁德)(?:科技|技术|网络|信息|数据|软件)?(?:有限(?:责任)?公司|股份(?:有限)?公司|集团有限公司|科技有限公司|有限公司|集团)?',
    "person_name": r'(?:[张王李赵刘陈杨黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹易常武乔贺赖龚文]|\u2C7B[一-龥])(?:\u2C7B[一-龥])',
    "phone_cn": r'(?:1[3-9]\d{1}[-\s]?\d{4}[-\s]?\d{4}|\+86[-\s]?1[3-9]\d{1}[-\s]?\d{4}[-\s]?\d{4})',
    "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    "website": r'(?:https?://)?(?:www\.)?[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?',
    "job_title": r'(?:董事长|总经理|副总裁|总监|经理|主管|工程师|架构师|设计师|分析师|顾问|CEO|CTO|CFO|COO|VP|Director|Manager|Lead|Head of|SVP|EVP|Partner|President|Chairman)',
    "industry": r'(?:互联网|金融|医疗|教育|制造|零售|房地产|物流|能源|农业|娱乐|游戏|电商|AI|人工智能|大数据|云计算|区块链|物联网|半导体|新能源汽车|生物医药)',
    "city": r'(?:北京|上海|广州|深圳|杭州|成都|武汉|南京|西安|重庆|天津|苏州|郑州|长沙|东莞|青岛|厦门|合肥|福州|济南|大连|沈阳|昆明|贵阳|南宁|长春|哈尔滨|石家庄)',
    "registered_capital": r'(?:注册资本|注册资金|出资额)[：:]\s*[\d,.]+\s*万?(?:元|人民币)?',
}

_PRECOMPILED = {k: re.compile(v) for k, v in _FIELD_PATTERNS.items()}


class Extractor:
    """SLM 字段抽取器"""

    def __init__(self):
        pass

    # ── Public API ─────────────────────────────────────────────

    async def extract(
        self,
        text: str,
        fields: list[str] | None = None,
        context_tag: str = "default",
    ) -> ExtractResult:
        """从文本中抽取指定字段。

        Args:
            text: 源文本
            fields: 要抽取的字段名列表 (None = 全部)
            context_tag: 上下文

        Returns:
            ExtractResult
        """
        t0 = time.perf_counter()

        if not text.strip():
            return ExtractResult(
                capability=SLMCapability.EXTRACT,
                model="heuristic_extractor",
                data=ExtractData(fields=[], text_length=0),
                confidence=0.0,
                latency_ms=0,
            )

        target_fields = fields or list(_FIELD_PATTERNS.keys())
        extracted: list[ExtractedField] = []

        for field_name in target_fields:
            pattern = _PRECOMPILED.get(field_name)
            if not pattern:
                continue

            # 从文本中找匹配
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                span_start = match.start()
                # 取匹配前后各 20 字作为上下文
                span_end = min(match.end(), len(text))
                context_start = max(0, span_start - 10)
                context_end = min(len(text), span_end + 10)
                source_span = text[context_start:context_end]

                extracted.append(ExtractedField(
                    field_name=field_name,
                    value=value,
                    confidence=_compute_field_confidence(field_name, value, text),
                    source_span=source_span,
                ))

        latency = (time.perf_counter() - t0) * 1000

        # 置信度: 基于找到的字段数和文本长度
        found = len(extracted)
        expected = len(target_fields)
        confidence = min(0.9, (found / max(expected, 1)) * 0.7 + 0.2) if expected > 0 else 0.0

        return ExtractResult(
            capability=SLMCapability.EXTRACT,
            model="heuristic_extractor",
            data=ExtractData(
                fields=extracted,
                text_length=len(text),
                fields_found=found,
            ),
            confidence=round(confidence, 4),
            latency_ms=latency,
            needs_escalation=(confidence < 0.4 and len(text) > 50),
            escalation_reason="Low extraction yield" if confidence < 0.4 and len(text) > 50 else "",
        )

    # ── 快捷方法 ───────────────────────────────────────────────

    async def extract_company_fields(self, text: str) -> ExtractResult:
        """抽取企业字段: 公司名/电话/邮箱/网站/职位/城市"""
        return await self.extract(text, fields=[
            "company_name", "phone_cn", "email", "website",
            "job_title", "industry", "city",
        ], context_tag="company_fields")

    async def extract_person_fields(self, text: str) -> ExtractResult:
        """抽取人物字段: 人名/电话/邮箱/职位"""
        return await self.extract(text, fields=[
            "person_name", "phone_cn", "email", "job_title",
        ], context_tag="person_fields")

    async def extract_risk_fields(self, text: str) -> ExtractResult:
        """抽取风险相关字段"""
        return await self.extract(
            text,
            fields=["registered_capital", "company_name", "city"],
            context_tag="risk_fields",
        )


def _compute_field_confidence(field_name: str, value: str, full_text: str) -> float:
    """根据字段类型计算置信度"""
    base = 0.7

    # 长度检查
    if field_name == "phone_cn" and re.match(r'^1[3-9]\d{9}$', value.replace(" ", "").replace("-", "")):
        base = 0.95
    elif field_name == "email" and "@" in value and "." in value:
        base = 0.95
    elif field_name == "website" and "." in value:
        base = 0.85
    elif field_name == "company_name" and len(value) >= 6:
        base = 0.8
    elif field_name == "person_name" and 2 <= len(value) <= 4:
        base = 0.6  # 人名抽取置信度中等

    # 重复出现加分
    if full_text.count(value) > 1:
        base = min(1.0, base + 0.1)

    return round(base, 4)
