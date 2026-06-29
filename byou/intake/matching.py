# byou/intake/matching.py
"""Similarity & Cross-Session Matching Engine.

Implements the "Matching" phase of the Intake pipeline:
  - Fuzzy name matching (Chinese name variants, pinyin, truncation)
  - Phone number normalization (+86-138-xxxx / 138xxxx / 86138xxxx)
  - Email normalization (gmail.com vs googlemail.com, +suffix)
  - Company name variant matching (Ltd/Co.,Ltd/有限责任公司)
  - Cross-session identity deduplication

Design:
  - All matchers are stateless functions → easy to test, easy to swap.
  - SimilarityEngine combines weighted scores from each matcher.
  - CrossSessionMatcher uses IdentityGraph as the identity index.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from byou.intake.identity.graph import IdentityGraph, NodeType

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════
#  Phone Normalization
# ═════════════════════════════════════════════════════════

_CN_MOBILE_PREFIXES = ("130", "131", "132", "133", "134", "135", "136",
                        "137", "138", "139", "150", "151", "152", "153",
                        "155", "156", "157", "158", "159", "170", "171",
                        "172", "173", "175", "176", "177", "178", "180",
                        "181", "182", "183", "184", "185", "186", "187",
                        "188", "189", "190", "191", "192", "193", "195",
                        "196", "197", "198", "199")


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164-like format: 8613800138000.

    Handles:
      - +86-138-0000-0000  → 8613800000000
      - 138 0000 0000        → 8613800000000
      - 0138-0000-0000       → 8613800000000  (strip leading 0)
      - 8613800000000         → 8613800000000  (already normalized)
      - 13800000000           → 8613800000000  (add CN prefix)
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)

    # Strip leading 0 (domestic dialing prefix)
    if digits.startswith("0") and len(digits) > 11:
        digits = digits[1:]

    # Add CN country code if missing
    if len(digits) == 11 and digits[:3] in _CN_MOBILE_PREFIXES:
        digits = "86" + digits
    elif len(digits) == 13 and digits.startswith("86"):
        pass  # already has country code
    else:
        # Best-effort: keep digits as-is
        pass

    return digits


# ═════════════════════════════════════════════════════════
#  Email Normalization
# ═════════════════════════════════════════════════════════

_EMAIL_ALIAS_MAP = {
    "gmail.com": {"googlemail.com"},
    "googlemail.com": {"gmail.com"},
    "outlook.com": {"hotmail.com", "live.com"},
    "hotmail.com": {"outlook.com", "live.com"},
    "qq.com": {"foxmail.com"},
    "foxmail.com": {"qq.com"},
}


def normalize_email(email: str) -> str:
    """Normalize an email address for matching.

    Handles:
      - case folding (Gmail is case-insensitive)
      - +suffix stripping (foo+tag@gmail.com → foo@gmail.com)
      - alias domain mapping (googlemail.com → gmail.com)
    """
    if not email:
        return ""
    email = email.strip().lower()

    try:
        local, domain = email.rsplit("@", 1)
    except ValueError:
        return email

    # Strip +suffix
    local = local.split("+")[0]

    # Domain alias mapping
    domain = _EMAIL_ALIAS_MAP.get(domain, {domain}).pop() if domain in _EMAIL_ALIAS_MAP else domain

    return f"{local}@{domain}"


# ═════════════════════════════════════════════════════════
#  Name Similarity (Chinese-aware)
# ═════════════════════════════════════════════════════════

def _tokenize_name(name: str) -> list[str]:
    """Tokenize a Chinese/English name into comparable units."""
    if not name:
        return []
    name = name.strip()
    # Extract Chinese characters only
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", name)
    # Extract Latin words
    latin_words = re.findall(r"[a-zA-Z]+", name)
    return chinese_chars + [w.lower() for w in latin_words]


def name_similarity(a: str, b: str) -> float:
    """Compute name similarity score in [0, 1].

    Strategy (max of):
      1. Exact match after normalization
      2. SequenceMatcher on full strings
      3. Character-set Jaccard (Chinese chars)
      4. Pinyin-aware match (simplified: check if one is substring of other)

    Returns: 0.0 = completely different, 1.0 = match
    """
    if not a or not b:
        return 0.0

    na = a.strip().lower()
    nb = b.strip().lower()

    # 1. Exact match
    if na == nb:
        return 1.0

    # 2. SequenceMatcher
    seq_score = SequenceMatcher(None, na, nb).ratio()

    # 3. Character-level Jaccard for Chinese
    ca = set(re.findall(r"[\u4e00-\u9fff]", na))
    cb = set(re.findall(r"[\u4e00-\u9fff]", nb))
    char_score = 0.0
    if ca and cb:
        intersection = len(ca & cb)
        union = len(ca | cb)
        char_score = intersection / union if union > 0 else 0.0
        # Boost if all chars in shorter name appear in longer name
        if ca <= cb and ca & cb == ca:
            char_score = max(char_score, 0.85)
        elif cb <= ca and cb & ca == cb:
            char_score = max(char_score, 0.85)

    # 4. Substring match (handles "Zhang Wei" vs "Wei Zhang" partially)
    if len(na) >= 4 and na in nb or len(nb) >= 4 and nb in na:
        substr_score = 0.8
    else:
        substr_score = 0.0

    return max(seq_score, char_score, substr_score)


# ═════════════════════════════════════════════════════════
#  Company Name Similarity
# ═════════════════════════════════════════════════════════

_COMPANY_SUFFIXES = [
    ("有限公司", {"limited", "ltd", "co.,ltd", "co., ltd"}),
    ("有限责任公司", {"limited", "ltd"}),
    ("股份有限公司", {"inc", "corp", "corporation"}),
    ("集团", {"group", "holdings", "holding"}),
    ("科技", {"tech", "technology", "technologies"}),
    ("信息", {"information", "info"}),
    ("网络", {"network", "net"}),
    ("软件", {"software", "soft"}),
]


def normalize_company_name(name: str) -> str:
    """Normalize a company name for matching.

    Strips common suffixes and normalizes to lowercase ASCII where possible.
    """
    if not name:
        return ""
    n = name.strip().lower()
    # Remove common suffixes for comparison
    for cn_suffix, en_aliases in _COMPANY_SUFFIXES:
        n = n.replace(cn_suffix, "")
        for alias in en_aliases:
            n = n.replace(alias, "")
    # Remove punctuation
    n = re.sub(r"[,\.\(\)（）【】\[\]\s\-&]", "", n)
    return n


def company_similarity(a: str, b: str) -> float:
    """Compute company name similarity."""
    if not a or not b:
        return 0.0
    na = normalize_company_name(a)
    nb = normalize_company_name(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


# ═════════════════════════════════════════════════════════
#  SimilarityEngine
# ═════════════════════════════════════════════════════════

# Weight configuration for combined similarity
DEFAULT_WEIGHTS = {
    "name": 0.35,
    "phone": 0.25,
    "email": 0.25,
    "company": 0.15,
}


@dataclass
class MatchScore:
    """Detailed similarity score between two identity records."""
    overall: float = 0.0
    name_score: float = 0.0
    phone_score: float = 0.0
    email_score: float = 0.0
    company_score: float = 0.0
    matched_fields: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 4),
            "name": round(self.name_score, 4),
            "phone": round(self.phone_score, 4),
            "email": round(self.email_score, 4),
            "company": round(self.company_score, 4),
            "matched_fields": self.matched_fields,
            "evidence": self.evidence,
        }


class SimilarityEngine:
    """Compute multi-field similarity between two identity records.

    Each record is a dict with optional keys:
      {name, phone, email, company}

    Returns a MatchScore with weighted overall score.
    """

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    def compare(self, rec_a: dict[str, Any], rec_b: dict[str, Any]) -> MatchScore:
        score = MatchScore()

        # Name
        name_a = rec_a.get("name", "")
        name_b = rec_b.get("name", "")
        if name_a and name_b:
            score.name_score = name_similarity(name_a, name_b)
            if score.name_score >= 0.7:
                score.matched_fields.append("name")
                score.evidence.append(f"name:{score.name_score:.2f}")

        # Phone (normalize first)
        phone_a = normalize_phone(rec_a.get("phone", ""))
        phone_b = normalize_phone(rec_b.get("phone", ""))
        if phone_a and phone_b:
            score.phone_score = 1.0 if phone_a == phone_b else 0.0
            if score.phone_score >= 0.7:
                score.matched_fields.append("phone")
                score.evidence.append(f"phone:{phone_a}")

        # Email (normalize first)
        email_a = normalize_email(rec_a.get("email", ""))
        email_b = normalize_email(rec_b.get("email", ""))
        if email_a and email_b:
            score.email_score = 1.0 if email_a == email_b else 0.0
            if score.email_score >= 0.7:
                score.matched_fields.append("email")
                score.evidence.append(f"email:{email_a}")

        # Company
        company_a = rec_a.get("company", "")
        company_b = rec_b.get("company", "")
        if company_a and company_b:
            score.company_score = company_similarity(company_a, company_b)
            if score.company_score >= 0.7:
                score.matched_fields.append("company")
                score.evidence.append(f"company:{score.company_score:.2f}")

        # Weighted overall (only count fields that are present in BOTH records)
        present_fields = []
        if name_a and name_b:
            present_fields.append(("name", score.name_score))
        if phone_a and phone_b:
            present_fields.append(("phone", score.phone_score))
        if email_a and email_b:
            present_fields.append(("email", score.email_score))
        if company_a and company_b:
            present_fields.append(("company", score.company_score))

        if present_fields:
            weighted_sum = sum(
                self.weights.get(f, 0) * s for f, s in present_fields
            )
            weight_total = sum(self.weights.get(f, 0) for f, _ in present_fields)
            score.overall = weighted_sum / weight_total if weight_total > 0 else 0.0

        return score


# ═════════════════════════════════════════════════════════
#  CrossSessionMatcher
# ═════════════════════════════════════════════════════════

from enum import Enum


class MatchDecision(Enum):
    AUTO_MERGE = "auto_merge"      # score ≥ 0.85 → auto-merge
    SUGGEST_MERGE = "suggest"      # 0.6 ≤ score < 0.85 → suggest
    AMBIGUOUS = "ambiguous"        # multiple candidates, unsure
    NO_MATCH = "no_match"           # score < 0.4


@dataclass
class CrossSessionMatch:
    """Result of cross-session matching for one PersonCandidate."""
    decision: MatchDecision
    best_uid: str = ""
    best_score: float = 0.0
    all_candidates: list[dict[str, Any]] = field(default_factory=list)
    matched_fields: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    requires_review: bool = False
    review_reason: str = ""


class CrossSessionMatcher:
    """Match current intake identities against historical identity graph.

    Uses SimilarityEngine to compare current BusinessCard fields
    against all known UIDs in the IdentityGraph.

    Thresholds:
      ≥ 0.85  → AUTO_MERGE (auto-confirm)
      ≥ 0.60  → SUGGEST_MERGE (queue for review)
      ≥ 0.40  → AMBIGUOUS (multiple candidates)
      < 0.40  → NO_MATCH (create new UID)
    """

    def __init__(
        self,
        identity_graph: IdentityGraph,
        similarity_engine: SimilarityEngine | None = None,
    ):
        self._graph = identity_graph
        self._engine = similarity_engine or SimilarityEngine()

    def match_card(
        self,
        card: dict[str, Any],
        threshold_auto: float = 0.85,
        threshold_suggest: float = 0.60,
    ) -> CrossSessionMatch:
        """Match a business card against all known UIDs in the graph."""
        if self._graph is None:
            return CrossSessionMatch(decision=MatchDecision.NO_MATCH)
        uid_nodes = self._graph.find_by_type(NodeType.UID)
        if not uid_nodes:
            return CrossSessionMatch(decision=MatchDecision.NO_MATCH)

        candidates: list[dict[str, Any]] = []
        for node in uid_nodes:
            uid_rec = self._node_to_record(node)
            score = self._engine.compare(card, uid_rec)
            if score.overall >= 0.4:
                candidates.append({
                    "uid": node.node_id,
                    "score": score.overall,
                    "detail": score.to_dict(),
                    "label": node.label,
                })

        candidates.sort(key=lambda c: c["score"], reverse=True)

        if not candidates:
            return CrossSessionMatch(decision=MatchDecision.NO_MATCH)

        best = candidates[0]

        if best["score"] >= threshold_auto and len(candidates) == 1:
            return CrossSessionMatch(
                decision=MatchDecision.AUTO_MERGE,
                best_uid=best["uid"],
                best_score=best["score"],
                all_candidates=candidates[:3],
                matched_fields=best["detail"].get("matched_fields", []),
                evidence=best["detail"].get("evidence", []),
                requires_review=False,
            )

        if best["score"] >= threshold_auto and len(candidates) > 1:
            return CrossSessionMatch(
                decision=MatchDecision.AMBIGUOUS,
                best_uid=best["uid"],
                best_score=best["score"],
                all_candidates=candidates[:5],
                requires_review=True,
                review_reason=f"Multiple candidates: {[c['uid'] for c in candidates[:5]]}",
            )

        if best["score"] >= threshold_suggest:
            return CrossSessionMatch(
                decision=MatchDecision.SUGGEST_MERGE,
                best_uid=best["uid"],
                best_score=best["score"],
                all_candidates=candidates[:5],
                matched_fields=best["detail"].get("matched_fields", []),
                evidence=best["detail"].get("evidence", []),
                requires_review=True,
                review_reason=f"Suggest merge (score={best['score']:.2f})",
            )

        return CrossSessionMatch(
            decision=MatchDecision.NO_MATCH,
            best_uid=best["uid"],
            best_score=best["score"],
            all_candidates=candidates[:3],
        )

    def match_voiceprint(
        self,
        embedding: list[float],
        threshold_auto: float = 0.85,
    ) -> CrossSessionMatch:
        """Delegate voiceprint matching to the graph's match_voiceprint.
        
        If graph is None, return NO_MATCH.
        """
        from byou.intake.identity.graph import MatchDecisionType

        if self._graph is None:
            return CrossSessionMatch(
                decision=MatchDecision.NO_MATCH,
                best_uid="",
                best_score=0.0,
                all_candidates=[],
                requires_review=False,
                review_reason="no_graph",
            )

        result = self._graph.match_voiceprint(embedding, threshold_auto)
        decision_map = {
            MatchDecisionType.AUTO_MATCH: MatchDecision.AUTO_MERGE,
            MatchDecisionType.AMBIGUOUS: MatchDecision.AMBIGUOUS,
            MatchDecisionType.NO_MATCH: MatchDecision.NO_MATCH,
            MatchDecisionType.CONFLICT: MatchDecision.AMBIGUOUS,
        }
        return CrossSessionMatch(
            decision=decision_map.get(result.decision, MatchDecision.NO_MATCH),
            best_uid=result.candidates[0]["uid"] if result.candidates else "",
            best_score=result.candidates[0]["score"] if result.candidates else 0.0,
            all_candidates=result.candidates,
            requires_review=result.requires_review,
            review_reason=result.review_reason,
        )

    def match_person_candidate(
        self,
        candidate: dict[str, Any],
    ) -> CrossSessionMatch:
        """Match a PersonCandidate (card + optional voiceprint) against the graph.

        Strategy:
          1. If voiceprint embedding → match_voiceprint first
          2. If card → match_card
          3. Combine: voiceprint wins if high confidence, card confirms
        """
        card_rec = candidate.get("card", {})
        vp_emb = candidate.get("voiceprint_embedding", [])

        # Try voiceprint first
        if vp_emb:
            vp_result = self.match_voiceprint(vp_emb)
            if vp_result.decision == MatchDecision.AUTO_MERGE:
                return vp_result

        # Try card
        if card_rec:
            card_result = self.match_card(card_rec)
            if vp_emb and vp_result.best_uid and vp_result.best_score >= 0.6:
                # Voiceprint + card agree → boost confidence
                if vp_result.best_uid == card_result.best_uid:
                    return CrossSessionMatch(
                        decision=MatchDecision.AUTO_MERGE,
                        best_uid=vp_result.best_uid,
                        best_score=max(vp_result.best_score, card_result.best_score),
                        matched_fields=list(set(vp_result.matched_fields + card_result.matched_fields)),
                        evidence=vp_result.evidence + card_result.evidence,
                        requires_review=False,
                    )
                else:
                    # Conflict: voiceprint says A, card says B
                    return CrossSessionMatch(
                        decision=MatchDecision.AMBIGUOUS,
                        best_uid=vp_result.best_uid,
                        best_score=max(vp_result.best_score, card_result.best_score),
                        all_candidates=vp_result.all_candidates + card_result.all_candidates,
                        requires_review=True,
                        review_reason="voiceprint_card_conflict",
                    )
            return card_result

        if vp_emb:
            return vp_result

        return CrossSessionMatch(decision=MatchDecision.NO_MATCH)

    # ── Helpers ─────────────────────────────────────────

    def _node_to_record(self, node: Any) -> dict[str, Any]:
        """Convert an IdentityNode (UID) to a record for SimilarityEngine."""
        meta = node.metadata or {}
        return {
            "name": node.label,
            "phone": meta.get("phone", ""),
            "email": meta.get("email", ""),
            "company": meta.get("company", ""),
        }

    def bulk_match(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[CrossSessionMatch]:
        """Match multiple PersonCandidates in bulk."""
        return [self.match_person_candidate(c) for c in candidates]
