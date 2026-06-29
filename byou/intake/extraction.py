# byou/intake/extraction.py
"""Intake extraction orchestration layer.

Coordinates provider adapters (card / voiceprint / diarization) and
identity matching.  This is the orchestration layer — it calls into
sub-directory adapters, not the other way around.

Provider-specific parsing lives in:
  - byou/intake/card/adapter.py    (PaddleOCR → BusinessCard)
  - byou/intake/voiceprint/adapter.py  (WeSpeaker → VoiceprintProfile)
  - byou/intake/diarization/adapter.py (pyannote → SpeakerCluster[])

Models (intake-specific, never leak to Core):
  - byou/intake/models.py

Flow:
  RawIntakePackage
    → CardAdapter.process_batch()        → BusinessCard[]
    → VoiceprintAdapter.process_batch()  → VoiceprintProfile[]
    → DiarizationAdapter.process_batch() → SpeakerCluster[]
    → IdentityMatcher.match_all()        → PersonCandidate[]
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.card.adapter import CardAdapter
from byou.intake.diarization.adapter import DiarizationAdapter
from byou.intake.matching import CrossSessionMatcher, SimilarityEngine
from byou.intake.models import BusinessCard, PersonCandidate, SpeakerCluster, VoiceprintProfile
from byou.intake.voiceprint.adapter import VoiceprintAdapter
from byou.intake.voiceprint.extractor import (
    MockVoiceprintExtractor,
    VoiceprintExtractor,
)
from byou.intake.voiceprint.matcher import VoiceprintMatcher

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Extraction orchestrator
# ══════════════════════════════════════════════════════════

class ExtractionOrchestrator:
    """Orchestrate provider adapter calls for a single intake run.

    Usage:
        orch = ExtractionOrchestrator(identity_graph=...)
        cards = orch.extract_cards(raw_cards)
        vps = orch.extract_voiceprints(raw_vps)
        clusters = orch.extract_diarization(raw_di)
        candidates = orch.match_all(cards, vps, clusters)
    """

    def __init__(self, identity_graph=None, use_mock_extractor: bool = True):
        self._card = CardAdapter()
        self._voiceprint_adapter = VoiceprintAdapter()
        self._voiceprint_extractor = (
            MockVoiceprintExtractor() if use_mock_extractor
            else VoiceprintExtractor()
        )
        self._diarization = DiarizationAdapter()
        self._matcher = IdentityMatcher(identity_graph)
        self._use_mock = use_mock_extractor

    def extract_cards(self, raws: list[dict[str, Any]]) -> list[BusinessCard]:
        return self._card.process_batch(raws)

    def extract_voiceprints(self, raws: list[dict[str, Any]]) -> list[VoiceprintProfile]:
        """Adapt existing voiceprint data (WeSpeaker output)."""
        return self._voiceprint_adapter.process_batch(raws)

    async def extract_voiceprints_from_audio(
        self, audio_paths: list[str | Path]
    ) -> list[VoiceprintProfile]:
        """Extract voiceprints from audio files.

        Args:
            audio_paths: List of audio file paths.

        Returns:
            list[VoiceprintProfile]: Extracted profiles.
        """
        embeddings = await self._voiceprint_extractor.extract_batch(audio_paths)
        
        # Convert embeddings to VoiceprintProfile list
        profiles = []
        for i, emb in enumerate(embeddings):
            if emb:  # Skip empty embeddings
                profiles.append(VoiceprintProfile(
                    uid="",
                    embedding=emb,
                    source_audio_eid=str(audio_paths[i]),
                ))
        return profiles

    def extract_diarization(self, raw: dict[str, Any] | list[dict[str, Any]]) -> list[SpeakerCluster]:
        return self._diarization.process(raw)

    def set_use_real_extractor(self, use_real: bool = True) -> None:
        """Switch between mock and real extractor."""
        if use_real:
            self._voiceprint_extractor = VoiceprintExtractor()
            self._use_mock = False
        else:
            self._voiceprint_extractor = MockVoiceprintExtractor()
            self._use_mock = True

    def match_all(
        self,
        cards: list[BusinessCard],
        voiceprints: list[VoiceprintProfile],
        clusters: list[SpeakerCluster],
    ) -> list[PersonCandidate]:
        return self._matcher.match_all(cards, voiceprints, clusters)


# ══════════════════════════════════════════════════════════
# Identity matcher (orchestration)
# ══════════════════════════════════════════════════════════

class IdentityMatcher:
    """Match voiceprints and card data to known identities.

    v2: uses CrossSessionMatcher (fuzzy name/phone/email/company matching)
    instead of simple graph alias lookup.
    """

    def __init__(self, identity_graph=None, similarity_weights=None):
        self._graph = identity_graph
        self._engine = SimilarityEngine(weights=similarity_weights)
        self._cross_matcher = CrossSessionMatcher(identity_graph, self._engine)
        self._vp_matcher = VoiceprintMatcher(identity_graph)

    # ── Public API (delegates to CrossSessionMatcher) ──────────

    def match_voiceprint(self, embedding: list[float]) -> dict[str, Any]:
        """Match a voiceprint embedding → CrossSessionMatch result."""
        result = self._cross_matcher.match_voiceprint(embedding)
        return {
            "uid": result.best_uid,
            "score": result.best_score,
            "candidates": result.all_candidates,
            "decision": result.decision.value,
            "requires_review": result.requires_review,
            "matched_fields": result.matched_fields,
            "evidence": result.evidence,
        }

    def match_card_to_identity(self, card: BusinessCard) -> dict[str, Any]:
        """Match a business card → CrossSessionMatch result."""
        card_rec = {
            "name": card.name,
            "phone": card.phone,
            "email": card.email,
            "company": card.company,
        }
        result = self._cross_matcher.match_card(card_rec)
        return {
            "uid": result.best_uid,
            "score": result.best_score,
            "confidence": result.best_score,
            "candidates": result.all_candidates,
            "decision": result.decision.value,
            "requires_review": result.requires_review,
            "matched_fields": result.matched_fields,
            "evidence": result.evidence,
        }

    def match_person_candidate(
        self,
        candidate: dict[str, Any],
    ) -> CrossSessionMatch:
        """Match a PersonCandidate dict against the graph."""
        return self._cross_matcher.match_person_candidate(candidate)

    # ── PersonCandidate builder ─────────────────────────────

    def build_person_candidate(
        self,
        card: BusinessCard | None = None,
        voiceprint: VoiceprintProfile | None = None,
        voiceprint_match: dict[str, Any] | None = None,
    ) -> PersonCandidate:
        """Build a PersonCandidate from card and/or voiceprint data."""
        source_parts = []
        if card:
            source_parts.append("card")
        if voiceprint:
            source_parts.append("voiceprint")

        best_uid = ""
        best_score = 0.0
        candidates: list[dict[str, Any]] = []
        requires_review = False
        review_reason = ""

        # Voiceprint is primary evidence
        if voiceprint_match and voiceprint_match.get("uid"):
            best_uid = voiceprint_match["uid"]
            best_score = voiceprint_match.get("score", 0.0)
            candidates = voiceprint_match.get("candidates", [])
            requires_review = voiceprint_match.get("requires_review", False)

        # Card is secondary — use CrossSessionMatcher for proper matching
        if not best_uid and card:
            card_match = self.match_card_to_identity(card)
            if card_match["uid"]:
                best_uid = card_match["uid"]
                best_score = card_match["score"]
                candidates = card_match.get("candidates", [])
                requires_review = card_match.get("requires_review", False)
                if card_match.get("matched_fields"):
                    review_reason = f"matched on {card_match['matched_fields']}"

        # Card + voiceprint mismatch → conflict
        if card and voiceprint_match and voiceprint_match.get("uid"):
            card_match = self.match_card_to_identity(card)
            if card_match["uid"] and card_match["uid"] != voiceprint_match["uid"]:
                requires_review = True
                review_reason = "card_voice_mismatch"

        return PersonCandidate(
            source="+".join(source_parts) if source_parts else "unknown",
            card=card,
            voiceprint=voiceprint,
            best_match_uid=best_uid,
            best_match_score=best_score,
            match_candidates=candidates,
            requires_review=requires_review or (best_score < 0.5),
            review_reason=review_reason or ("no_match" if not best_uid else ""),
        )

    # ── Batch matching ─────────────────────────────────────

    def match_all(
        self,
        cards: list[BusinessCard],
        voiceprints: list[VoiceprintProfile],
        clusters: list[SpeakerCluster],
    ) -> list[PersonCandidate]:
        """Match all voiceprints and cards → PersonCandidate list."""
        candidates: list[PersonCandidate] = []
        matched_voiceprints: set[str] = set()
        matched_cards: set[str] = set()

        # (1) Voiceprint + card pairing
        for vp in voiceprints:
            vpid = vp.vpid
            if vpid in matched_voiceprints:
                continue

            vp_match = self.match_voiceprint(vp.embedding)

            # Find best-matching card by shared UID
            best_card = None
            best_card_score = 0.0
            for card in cards:
                cid = card.card_id
                if cid in matched_cards:
                    continue
                card_match = self.match_card_to_identity(card)
                if card_match["uid"] and card_match["uid"] == vp_match.get("uid", ""):
                    if card_match["score"] > best_card_score:
                        best_card_score = card_match["score"]
                        best_card = card

            if best_card:
                matched_cards.add(best_card.card_id)
                matched_voiceprints.add(vpid)
                candidates.append(self.build_person_candidate(
                    card=best_card, voiceprint=vp, voiceprint_match=vp_match,
                ))
            else:
                matched_voiceprints.add(vpid)
                candidates.append(self.build_person_candidate(
                    voiceprint=vp, voiceprint_match=vp_match,
                ))

        # (2) Remaining cards → card-only candidates
        for card in cards:
            if card.card_id in matched_cards:
                continue
            matched_cards.add(card.card_id)
            candidates.append(self.build_person_candidate(card=card))

        # (3) Unmatched speaker clusters → unknown candidates
        matched_count = sum(1 for c in candidates if c.voiceprint is not None)
        for _ in clusters:
            if matched_count >= len(clusters):
                break
            candidates.append(PersonCandidate(source="diarization", requires_review=False))
            matched_count += 1

        return candidates
