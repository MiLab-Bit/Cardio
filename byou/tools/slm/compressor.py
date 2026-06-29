"""SLM Compressor — 文本压缩器。

设计:
- 从长文本中提取关键句
- 去除冗余和低信息密度段落
- Heuristic: 位置加权 + 关键词密度
"""

from __future__ import annotations

import re
import time
from typing import Any

from .types import (
    CompressData,
    CompressResult,
    SLMCapability,
)

# ── 低信息密度句模式 ──────────────────────────────────────────

_NOISE_PATTERNS = [
    r'^(?:版权所有|copyright|©)\b',           # 版权信息
    r'^.{0,3}$',                               # 极短行
    r'^(?:更多|下一页|上一页|回到顶部|点击查看)',       # 导航
    r'^(?:Loading|请稍候|正在加载)',                # 加载
    r'^[#*\-=\s]+$',                             # 纯符号行
    r'^(?:电话|传真|邮箱|地址)[：:]\s*[\d@.\- ]+$',  # 纯联系方式行 (可能已在 OCR 层处理)
]


class Compressor:
    """SLM 文本压缩器"""

    def __init__(self):
        pass

    # ── Public API ─────────────────────────────────────────────

    async def compress(
        self,
        text: str,
        max_chars: int = 500,
        target_ratio: float = 0.3,
    ) -> CompressResult:
        """压缩文本。

        Args:
            text: 源文本
            max_chars: 最大输出字符数
            target_ratio: 目标压缩比 (0.3 = 压缩到 30%)

        Returns:
            CompressResult
        """
        t0 = time.perf_counter()

        if not text.strip():
            return CompressResult(
                capability=SLMCapability.COMPRESS,
                model="heuristic_compressor",
                data=CompressData(compressed_text="", original_length=0, compressed_length=0),
                confidence=0.0,
                latency_ms=0,
            )

        original_length = len(text)

        # 1. 拆句
        sentences = self._split_sentences(text)

        # 2. 过滤噪音
        clean = self._filter_noise(sentences)

        # 3. 打分 (位置 + 关键词)
        scored = self._score_sentences(clean)

        # 4. 选 top 句
        selected = self._select_top(scored, max_chars=max_chars)

        # 5. 组装
        compressed = "\n".join(selected)
        compressed_length = len(compressed)

        # 6. 抽取关键句 (前 3)
        key_sentences = selected[:3]

        latency = (time.perf_counter() - t0) * 1000

        # 置信度: 基于压缩比和句子数
        actual_ratio = compressed_length / max(original_length, 1)
        confidence = 0.7 if actual_ratio <= target_ratio else 0.5
        if len(clean) <= 5:
            confidence = 0.85  # 短文本压缩更容易

        return CompressResult(
            capability=SLMCapability.COMPRESS,
            model="heuristic_compressor",
            data=CompressData(
                compressed_text=compressed,
                original_length=original_length,
                compressed_length=compressed_length,
                key_sentences=key_sentences,
            ),
            confidence=round(confidence, 4),
            latency_ms=latency,
            needs_escalation=(confidence < 0.4 or compressed_length == 0),
            escalation_reason="Low compression quality" if confidence < 0.4 else "",
        )

    # ── 快捷方法 ───────────────────────────────────────────────

    async def compress_browser_snippet(self, html_text: str, max_chars: int = 400) -> CompressResult:
        """压缩浏览器返回的网页片段"""
        # 先从 HTML 中提取纯文本
        text = self._extract_text_from_html(html_text)
        return await self.compress(text, max_chars=max_chars, target_ratio=0.25)

    async def compress_research_summary(self, text: str, max_chars: int = 600) -> CompressResult:
        """压缩研究结果摘要"""
        return await self.compress(text, max_chars=max_chars, target_ratio=0.3)

    # ── 句子拆分 ───────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """按行 + 句末标点拆分"""
        # 先按行分
        lines = text.split("\n")
        result: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 按句末标点分
            parts = re.split(r'(?<=[。.！!？?\n])', line)
            for part in parts:
                part = part.strip()
                if part and len(part) >= 3:
                    result.append(part)
        return result

    @staticmethod
    def _filter_noise(sentences: list[str]) -> list[str]:
        """过滤低信息密度句"""
        result: list[str] = []
        for s in sentences:
            is_noise = False
            for pattern in _NOISE_PATTERNS:
                if re.search(pattern, s, re.IGNORECASE):
                    is_noise = True
                    break
            if not is_noise:
                result.append(s)
        return result

    @staticmethod
    def _score_sentences(sentences: list[str]) -> list[tuple[str, float]]:
        """为每个句子打分"""
        total = len(sentences)
        scored: list[tuple[str, float]] = []

        for i, s in enumerate(sentences):
            score = 0.0

            # 位置权重: 前 20% 和后 10% 加分
            position = i / max(total, 1)
            if position < 0.2:
                score += 0.3
            elif position > 0.9:
                score += 0.1

            # 内容密度
            # 包含数字 → 信息量高
            digits = len(re.findall(r'\d', s))
            score += min(0.2, digits * 0.05)

            # 包含专有名词 (大写单词 or 中文引号)
            proper_nouns = len(re.findall(r'[「」""]', s))
            score += min(0.15, proper_nouns * 0.05)

            # 包含关键词
            biz_keywords = r'公司|产品|服务|解决方案|市场|客户|收入|增长|合作|技术|平台|数据'
            kw_count = len(re.findall(biz_keywords, s))
            score += min(0.2, kw_count * 0.1)

            # 惩罚过短
            if len(s) < 10:
                score *= 0.5

            # 惩罚纯链接
            if re.match(r'^https?://\S+$', s):
                score *= 0.3

            scored.append((s, round(score, 4)))

        return scored

    @staticmethod
    def _select_top(
        scored_sentences: list[tuple[str, float]],
        max_chars: int = 500,
    ) -> list[str]:
        """按分数选出 top 句，直到字符数用尽"""
        # 按分数降序
        sorted_sents = sorted(scored_sentences, key=lambda x: -x[1])

        selected: list[str] = []
        char_count = 0

        for s, _score in sorted_sents:
            if char_count + len(s) > max_chars:
                break
            selected.append(s)
            char_count += len(s)

        return selected

    @staticmethod
    def _extract_text_from_html(html: str) -> str:
        """从 HTML 中提取纯文本"""
        # 移除 script, style
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 合并空白
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
