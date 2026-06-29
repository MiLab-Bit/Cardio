# byou/intake/handler.py
"""Intake Handler — main entry point for expo intake processing.

Flow: extract → assemble → publish

  RawIntakePackage (cards + voiceprints + speaker_clusters)
    → .handle()
    → extract (normalize to intake models)
    → assemble (build canonical types + seeds)
    → publish (dispatch to Memory/CRM/Audit/Review)
    → IntakeProcessingResult
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.assembly import CanonicalSessionAssembler
from byou.intake.extraction import ExtractionOrchestrator
from byou.intake.matching import CrossSessionMatcher, MatchDecision
from byou.intake.models import IntakeProcessingResult, PersonCandidate, RawIntakePackage
from byou.intake.publisher import IntakePublisher
from byou.intake.types import (
    IdentityGraphProtocol,
    MemoryGatewayProtocol,
    CRMGatewayProtocol,
    AuditGatewayProtocol,
    ReviewGatewayProtocol,
    ConversationGatewayProtocol,
)

logger = logging.getLogger(__name__)


class IntakeHandler:
    """Main entry point for Intake processing.

    Usage:
        handler = IntakeHandler(identity_graph, memory_gw, crm_gw, ...)
        result = await handler.handle(raw_package)
    """

    def __init__(
        self,
        identity_graph: IdentityGraphProtocol | None = None,
        memory_gateway: MemoryGatewayProtocol | None = None,
        crm_gateway: CRMGatewayProtocol | None = None,
        audit_gateway: AuditGatewayProtocol | None = None,
        review_gateway: ReviewGatewayProtocol | None = None,
        conversation_gateway: ConversationGatewayProtocol | None = None,
    ):
        self._identity_graph = identity_graph
        self._cross_session_matcher = (
            CrossSessionMatcher(identity_graph) if identity_graph else None
        )
        self._extractor = ExtractionOrchestrator(identity_graph)
        self._assembler = CanonicalSessionAssembler(identity_graph)
        self._publisher = IntakePublisher(
            memory_gateway=memory_gateway,
            crm_gateway=crm_gateway,
            audit_gateway=audit_gateway,
            review_gateway=review_gateway,
            conversation_gateway=conversation_gateway,
        )

    async def handle(
        self,
        raw: RawIntakePackage,
    ) -> IntakeProcessingResult:
        """Process a raw intake package through the full Intake pipeline.

        Args:
            raw: RawIntakePackage with cards, voiceprints, speaker_clusters

        Returns:
            IntakeProcessingResult with canonical_session, seeds, review flags
        """
        # ── Phase A+B+C: Extract + Match ───────────────
        # (1) Extract voiceprints FROM AUDIO if audio_paths provided
        audio_voiceprints: list[VoiceprintProfile] = []
        if raw.audio_paths:
            try:
                audio_voiceprints = await self._extractor.extract_voiceprints_from_audio(
                    raw.audio_paths
                )
                logger.info(
                    "Extracted %d voiceprints from %d audio files",
                    len(audio_voiceprints),
                    len(raw.audio_paths),
                )
            except Exception as e:
                logger.warning("Voiceprint extraction failed: %s", e)

        # (2) Also adapt any pre-computed voiceprint data
        voiceprints = self._extractor.extract_voiceprints(
            [v.model_dump() for v in raw.voiceprints]
        )
        # Merge: audio-extracted + pre-computed
        voiceprints.extend(audio_voiceprints)

        cards = self._extractor.extract_cards(
            [c.model_dump() for c in raw.cards]
        )
        clusters = self._extractor.extract_diarization(
            [c.model_dump() for c in raw.speaker_clusters]
        )
        person_candidates: list[PersonCandidate] = self._extractor.match_all(
            cards=cards,
            voiceprints=voiceprints,
            clusters=clusters,
        )

        # ── Cross-Session Matching ─────────────────────
        if self._cross_session_matcher:
            for candidate in person_candidates:
                card_rec: dict[str, Any] = {}
                if candidate.card:
                    card_rec = {
                        "name": candidate.card.name,
                        "phone": candidate.card.phone,
                        "email": candidate.card.email,
                        "company": candidate.card.company,
                    }
                vp_emb = (
                    candidate.voiceprint.embedding
                    if candidate.voiceprint
                    else []
                )

                match_result = self._cross_session_matcher.match_person_candidate(
                    {"card": card_rec, "voiceprint_embedding": vp_emb}
                )

                # Attach match result to candidate
                if match_result.best_uid:
                    candidate.best_match_uid = match_result.best_uid
                    candidate.best_match_score = match_result.best_score
                    candidate.match_candidates = [
                        {
                            "uid": c["uid"],
                            "score": c["score"],
                            "evidence": c.get("detail", {}).get("evidence", []),
                        }
                        for c in match_result.all_candidates
                    ]
                candidate.requires_review = match_result.requires_review
                candidate.review_reason = match_result.review_reason

                if match_result.decision == MatchDecision.AUTO_MERGE:
                    candidate.is_confirmed = True
                    candidate.confirmed_uid = match_result.best_uid

                logger.info(
                    "Cross-session match: person=%s decision=%s uid=%s score=%.2f",
                    candidate.person_id,
                    match_result.decision.value,
                    match_result.best_uid,
                    match_result.best_score,
                )

        # ── Phase D: Assemble ───────────────────────────
        assembled = self._assembler.assemble(
            session_id=raw.session_id,
            person_candidates=person_candidates,
            speaker_clusters=clusters,
            bd_staff_ids=raw.bd_staff_ids,
            venue=raw.venue,
            recorded_at=raw.recorded_at,
        )

        # ── Phase F: Publish ────────────────────────────
        result = await self._publisher.publish(
            session=assembled["session"],
            memory_seeds=assembled["memory_seeds"],
            crm_seeds=assembled["crm_seeds"],
            audit_entries=assembled["audit_entries"],
            review_required=assembled["review_required"],
        )

        logger.info(
            "Intake complete: sid=%s participants=%d turns=%d seeds=%d/%d/%d review=%s errors=%d",
            raw.session_id,
            len(assembled["session"].participants),
            len(assembled["session"].turns),
            len(assembled["memory_seeds"]),
            len(assembled["crm_seeds"]),
            len(assembled["audit_entries"]),
            assembled["review_required"],
            len(result.errors),
        )

        return result


