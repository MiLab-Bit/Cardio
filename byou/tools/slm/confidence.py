"""SLM Confidence — 置信度评分器。

用于:
- 判断 SLM 结果是否值得信任
- 为 escalation 决策提供信号
- 统一置信度计算
"""

from __future__ import annotations

import re
import time
from typing import Any

from .types import (
    ScoreData,
    ScoreResult,
    SLMCapability,
)


class ConfidenceScorer:
    """SLM 置信度评分器"""

    def __init__(self):
        pass

    # ── Public API ─────────────────────────────────────────────

    async def score(
        self,
        text: str,
        context_tag: str = "default",
    ) -> ScoreResult:
        """对文本做置信度评分"""
        t0 = time.perf_counter()

        if not text.strip():
            return ScoreResult(
                capability=SLMCapability.SCORE,
                model="heuristic_scorer",
                data=ScoreData(score=0.0, sub_scores={}, rationale="empty text"),
                confidence=0.0,
                latency_ms=0,
            )

        sub_scores: dict[str, float] = {}
        reasons: list[str] = []

        # 文本长度
        length_score = self._score_length(len(text))
        sub_scores["length"] = length_score
        if length_score < 0.5:
            reasons.append(f"text too short ({len(text)} chars)")

        # 信息密度
        density_score = self._score_density(text)
        sub_scores["density"] = density_score
        if density_score < 0.5:
            reasons.append("low information density")

        # 噪音比
        noise_ratio = self._score_noise_ratio(text)
        sub_scores["noise_ratio"] = noise_ratio
        if noise_ratio < 0.5:
            reasons.append("high noise ratio")

        # 结构化程度
        structure_score = self._score_structure(text)
        sub_scores["structure"] = structure_score

        # 综合评分 (加权平均)
        weights = {"length": 0.3, "density": 0.25, "noise_ratio": 0.25, "structure": 0.2}
        overall = sum(sub_scores[k] * weights.get(k, 0.25) for k in sub_scores)
        overall = round(min(1.0, max(0.0, overall)), 4)

        latency = (time.perf_counter() - t0) * 1000

        return ScoreResult(
            capability=SLMCapability.SCORE,
            model="heuristic_scorer",
            data=ScoreData(
                score=overall,
                sub_scores=sub_scores,
                rationale="; ".join(reasons) if reasons else "acceptable quality",
            ),
            confidence=overall,
            latency_ms=latency,
        )

    # ── Quick methods ─────────────────────────────────────────

    async def score_slm_result(self, result_text: str, confidence: float = 0.5) -> ScoreResult:
        """为 SLM 结果打分"""
        s = await self.score(result_text)
        # 混合 SLM 自身置信度和文本质量分数
        combined = (s.data.score + confidence) / 2 if s.data else confidence
        s.data = ScoreData(
            score=round(combined, 4),
            sub_scores={**(s.data.sub_scores if s.data else {}), "slm_confidence": confidence},
            rationale=s.data.rationale if s.data else "",
        )
        return s

    # ── Scoring components ────────────────────────────────────

    @staticmethod
    def _score_length(text_len: int) -> float:
        """文本长度评分: 50-500 字最佳"""
        if text_len < 10:
            return 0.1
        if text_len < 30:
            return 0.3
        if 50 <= text_len <= 500:
            return 1.0
        if text_len < 1000:
            return 0.8
        if text_len < 3000:
            return 0.6
        return 0.4

    @staticmethod
    def _score_density(text: str) -> float:
        """信息密度评分"""
        # 实体密度 (专有名词 + 数字)
        entities = len(re.findall(r'[「」""]|《[^》]+》', text))
        numbers = len(re.findall(r'\d{2,}', text))

        density = (entities * 0.3 + numbers * 0.1) / max(len(text) / 100, 1)
        return round(min(1.0, density), 4)

    @staticmethod
    def _score_noise_ratio(text: str) -> float:
        """噪音比评分 (越低越好 → 分数越高)"""
        # 标点/空白比
        punctuation = len(re.findall(r'[，。,.;；;、：:（）()【】\[\]\s]', text))
        ratio = 1.0 - (punctuation / max(len(text), 1))
        return round(min(1.0, max(0.0, ratio)), 4)

    @staticmethod
    def _score_structure(text: str) -> float:
        """结构化程度评分"""
        score = 0.0
        # 有换行 → +0.3
        if "\n" in text:
            score += 0.3
        # 有制表符 → +0.2
        if "\t" in text or "    " in text:
            score += 0.2
        # 有编号/列表 → +0.3
        if re.search(r'^\s*(?:\d+[.、]|[•\-\*\+])', text, re.MULTILINE):
            score += 0.3
        # 有标签格式 → +0.2
        if re.search(r'[A-Z_]{3,}:', text):
            score += 0.2
        return min(1.0, score)
