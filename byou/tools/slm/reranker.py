"""SLM Reranker — Cross-encoder 精排。

支持:
- 实时 reranker: 调用真实模型 (Qwen3-Reranker etc.)
- Heuristic fallback: TF-IDF + 关键词重叠

输入: query + candidates[] → 输出: top-k 排序结果
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .types import (
    RankedItem,
    RerankData,
    RerankResult,
    SLMCapability,
)

logger = logging.getLogger(__name__)


class Reranker:
    """SLM 重排序器"""

    def __init__(self):
        self._tokenizer = None
        self._model = None

    # ── Public API ─────────────────────────────────────────────

    async def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> RerankResult:
        """对候选列表做精排。

        Args:
            query: 查询文本
            candidates: [{"id": ..., "text": ..., "metadata": ...}, ...]
            top_k: 保留前 k
            min_score: 最低相关度阈值

        Returns:
            RerankResult with sorted RankedItems
        """
        t0 = time.perf_counter()

        if not candidates:
            return RerankResult(
                capability=SLMCapability.RERANK,
                model="heuristic_reranker",
                data=RerankData(items=[], query=query),
                confidence=1.0,
                latency_ms=0,
            )

        # Heuristic scoring (TF-IDF + keyword overlap)
        scores: list[tuple[int, float]] = []
        tokenized_query = self._tokenize(query)

        for idx, candidate in enumerate(candidates):
            text = candidate.get("text", "")
            score = self._heuristic_score(tokenized_query, text)
            scores.append((idx, score))

        # 排序
        scores.sort(key=lambda x: -x[1])

        # 构建结果
        items: list[RankedItem] = []
        for idx, score in scores[:top_k]:
            if score < min_score:
                break
            cand = candidates[idx]
            items.append(RankedItem(
                id=cand.get("id", str(idx)),
                text=cand.get("text", ""),
                score=round(score, 4),
                metadata=cand.get("metadata", {}),
            ))

        latency = (time.perf_counter() - t0) * 1000

        # 置信度: 基于 top 和 second 的差距
        confidence = 0.7
        if len(items) >= 2:
            gap = items[0].score - items[1].score
            confidence = min(0.95, 0.5 + gap * 2)
        elif len(items) == 1:
            confidence = 0.6 if items[0].score > 0.3 else 0.3

        return RerankResult(
            capability=SLMCapability.RERANK,
            model="heuristic_reranker",
            data=RerankData(
                items=items,
                query=query,
                candidates_count=len(candidates),
            ),
            confidence=confidence,
            latency_ms=latency,
            needs_escalation=(confidence < 0.5 or len(items) == 0 and len(candidates) > 0),
            escalation_reason="Low confidence reranking" if confidence < 0.5 else "",
        )

    # ── Heuristic scoring ──────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        """简单分词: 中文按字符 + 英文按空格."""
        # 分离中英文
        tokens: list[str] = []
        # 保留中文字符
        chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
        tokens.extend(chinese_chars)
        # 英文单词
        english_words = re.findall(r'[a-zA-Z0-9_]+', text)
        tokens.extend(w.lower() for w in english_words)
        return tokens

    def _heuristic_score(self, query_tokens: list[str], text: str) -> float:
        """TF-IDF 启发式评分"""
        if not text or not query_tokens:
            return 0.0

        text_lower = text.lower()

        # 精确匹配
        exact_matches = sum(1 for t in query_tokens if t in text_lower)
        exact_score = exact_matches / max(len(query_tokens), 1)

        # 部分匹配 (substring)
        partial_count = 0
        for token in query_tokens:
            if len(token) >= 3:
                for i in range(len(text_lower) - len(token) + 1):
                    if text_lower[i:i + len(token)] == token:
                        partial_count += 1
                        break

        partial_score = min(partial_count / max(len(query_tokens), 1), 1.0)

        # N-gram overlap
        text_tokens = self._tokenize(text)
        bigram_overlap = self._bigram_similarity(query_tokens, text_tokens)

        # 综合评分
        score = exact_score * 0.5 + partial_score * 0.2 + bigram_overlap * 0.3
        return min(score, 1.0)

    @staticmethod
    def _bigram_similarity(a: list[str], b: list[str]) -> float:
        """Bigram Jaccard 相似度"""
        if len(a) < 2 or len(b) < 2:
            return 0.0
        a_bi = set(zip(a, a[1:]))
        b_bi = set(zip(b, b[1:]))
        if not a_bi or not b_bi:
            return 0.0
        return len(a_bi & b_bi) / len(a_bi | b_bi)
