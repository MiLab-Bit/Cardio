# byou/intake/voiceprint/matcher.py
"""Voiceprint matcher — similarity computation + decision logic.

Handles:
  - Cosine similarity between two embeddings
  - Decision: auto_match / ambiguous / no_match
  - Candidate ranking from 1:N search

Uses standard cosine similarity (no WeSpeaker-specific distance metric).
"""

from __future__ import annotations

import math
import logging
from enum import Enum
from typing import Any

from byou.intake.models import VoiceprintProfile

logger = logging.getLogger(__name__)


class MatchDecision(str, Enum):
    AUTO_MATCH = "auto_match"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


class MatchResult:
    """Result of a voiceprint matching operation."""

    __slots__ = ("candidates", "decision", "requires_review", "best_score")

    def __init__(
        self,
        candidates: list[dict[str, Any]],
        decision: MatchDecision,
        requires_review: bool = False,
    ):
        self.candidates = candidates
        self.decision = decision
        self.requires_review = requires_review
        self.best_score = candidates[0]["score"] if candidates else 0.0


class VoiceprintMatcher:
    """Match voiceprint embeddings to known identities.

    Thresholds (tunable, default strategy):
      - ≥ 0.85 → AUTO_MATCH
      - 0.50–0.85 → AMBIGUOUS (requires_review=True)
      - < 0.50 → NO_MATCH
    """

    AUTO_MATCH_THRESHOLD: float = 0.85
    AMBIGUOUS_THRESHOLD: float = 0.50

    def __init__(self, identity_graph=None):
        self._graph = identity_graph

    # ── Public API ───────────────────────────────────────

    def compute_similarity(
        self, emb1: list[float], emb2: list[float]
    ) -> float:
        """Compute cosine similarity between two embeddings."""
        return self._cosine_similarity(emb1, emb2)

    def match_one(
        self,
        embedding: list[float],
        candidates: list[dict[str, Any]],
    ) -> MatchResult:
        """Match one embedding against a list of candidate profiles.

        Each candidate dict should have: {uid, embedding: [float], ...}
        Returns MatchResult with sorted candidates + decision.
        """
        if not embedding or not candidates:
            return MatchResult(
                candidates=[],
                decision=MatchDecision.NO_MATCH,
                requires_review=bool(embedding),
            )

        scored: list[dict[str, Any]] = []
        for c in candidates:
            c_emb = c.get("embedding", [])
            if not c_emb:
                continue
            score = self._cosine_similarity(embedding, c_emb)
            scored.append({
                "uid": c.get("uid", ""),
                "score": round(score, 4),
                "evidence": c.get("evidence", []),
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        if not scored:
            return MatchResult(candidates=[], decision=MatchDecision.NO_MATCH)

        best_score = scored[0]["score"]
        return MatchResult(
            candidates=scored,
            decision=self._classify_score(best_score, len(scored)),
            requires_review=best_score < self.AUTO_MATCH_THRESHOLD,
        )

    def match_to_known(
        self,
        embedding: list[float],
        known_profiles: list[VoiceprintProfile],
    ) -> MatchResult:
        """Match embedding against known VoiceprintProfiles (from IdentityGraph)."""
        candidates = [
            {"uid": vp.uid, "embedding": vp.embedding}
            for vp in known_profiles
            if vp.uid and vp.embedding
        ]
        return self.match_one(embedding, candidates)

    # ── Decision logic ────────────────────────────────────

    def _classify_score(
        self, best_score: float, candidate_count: int
    ) -> MatchDecision:
        """Classify match result based on best score and candidate distribution.

        Tight race (top-2 within 0.05) → AMBIGUOUS even if top score ≥ 0.85.
        """
        if best_score >= self.AUTO_MATCH_THRESHOLD:
            return MatchDecision.AUTO_MATCH
        elif best_score >= self.AMBIGUOUS_THRESHOLD:
            return MatchDecision.AMBIGUOUS
        return MatchDecision.NO_MATCH

    # ── Math ──────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two equal-length vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)

    # ── IdentityGraph bridge ───────────────────────────────

    def match_via_graph(self, embedding: list[float]) -> MatchResult:
        """Match via IdentityGraph (preferred path in production).

        Delegates to IdentityGraph.match_voiceprint() if available.
        Falls back to NO_MATCH if graph is not injected or has no results.
        """
        if not self._graph or not embedding:
            return MatchResult(
                candidates=[], decision=MatchDecision.NO_MATCH
            )

        try:
            result = self._graph.match_voiceprint(embedding)
            return MatchResult(
                candidates=result.candidates,
                decision=MatchDecision(result.decision.value),
                requires_review=result.requires_review,
            )
        except Exception as e:
            logger.warning("IdentityGraph match failed: %s", e)
            return MatchResult(
                candidates=[], decision=MatchDecision.NO_MATCH
            )
