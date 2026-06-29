# byou/intake/assembly.py
"""Canonical Session Assembler — intake models → canonical types.

Takes extraction results (BusinessCard, VoiceprintProfile, SpeakerCluster,
PersonCandidate) and assembles them into:
  - CanonicalSession
  - CanonicalParticipant[]
  - CanonicalTurn[]
  - MemorySeed[]
  - CRMSeed[]
  - AuditEntry[]

Key constraints enforced:
  - Transcript text in CanonicalTurn is truncated (≤500 chars)
  - MemorySeed contains NO raw transcript
  - CRMSeed contains ONLY actionable insight
  - AuditEntry references EIDs, not full data
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from byou.intake.models import (
    BusinessCard,
    PersonCandidate,
    SpeakerCluster,
    VoiceprintProfile,
)
from byou.models.channel_contract import (
    AuditEntry,
    CRMSeed,
    CanonicalParticipant,
    CanonicalSession,
    CanonicalTurn,
    MemorySeed,
)

logger = logging.getLogger(__name__)


class CanonicalSessionAssembler:
    """Assemble extraction results → canonical types.

    Usage:
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[...],
            speaker_clusters=[...],
            card_transcripts=None,   # optional: per-speaker turn text
            bd_staff_ids=["bid_001"],
            venue={},
        )
    """

    def __init__(self, identity_graph=None):
        self._graph = identity_graph

    def assemble(
        self,
        *,
        session_id: str,
        person_candidates: list[PersonCandidate] | None = None,
        speaker_clusters: list[SpeakerCluster] | None = None,
        card_transcripts: dict[str, list[str]] | None = None,
        bd_staff_ids: list[str] | None = None,
        venue: dict[str, str] | None = None,
        recorded_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Main assembly entry point.

        Returns dict with keys: session, memory_seeds, crm_seeds, audit_entries,
        review_required
        """
        candidates = person_candidates or []
        clusters = speaker_clusters or []
        bd_ids = bd_staff_ids or []

        # ── Build participants ──
        participants = self._build_participants(candidates, clusters, bd_ids)

        # ── Build turns ──
        turns = self._build_turns(clusters, card_transcripts)

        # ── Build session ──
        session = CanonicalSession(
            sid=session_id,
            session_type="expo",
            participants=participants,
            turns=turns,
            venue=venue or {},
            recorded_at=recorded_at or datetime.now(timezone.utc),
            duration_ms=self._calc_duration(turns),
            evidence_refs=self._collect_evidence(candidates, clusters),
            review_required=any(
                c.requires_review for c in candidates
            ),
        )

        # ── Build seeds ──
        memory_seeds = self._build_memory_seeds(session_id, candidates)
        crm_seeds = self._build_crm_seeds(candidates)
        audit_entries = self._build_audit_entries(session_id, candidates, clusters)

        return {
            "session": session,
            "memory_seeds": memory_seeds,
            "crm_seeds": crm_seeds,
            "audit_entries": audit_entries,
            "review_required": session.review_required,
        }

    # ── Participants ────────────────────────────────────

    def _build_participants(
        self,
        candidates: list[PersonCandidate],
        clusters: list[SpeakerCluster],
        bd_ids: list[str],
    ) -> list[CanonicalParticipant]:
        participants: list[CanonicalParticipant] = []

        # BD staff first (known identities)
        for i, bid in enumerate(bd_ids):
            participants.append(CanonicalParticipant(
                participant_id=f"P{i}",
                role="bd_staff",
                identity_status="confirmed",
                identity_ref=bid,
                identity_confidence=1.0,
                display_name=f"BD-{bid}",
            ))

        # External visitors (from person candidates)
        next_id = len(participants)
        for candidate in candidates:
            identity_status = "unknown"
            identity_ref = None
            confidence = 0.0

            if candidate.is_confirmed and candidate.confirmed_uid:
                identity_status = "confirmed"
                identity_ref = candidate.confirmed_uid
                confidence = 1.0
            elif candidate.best_match_uid and candidate.best_match_score >= 0.85:
                identity_status = "confirmed"
                identity_ref = candidate.best_match_uid
                confidence = candidate.best_match_score
            elif candidate.best_match_uid and candidate.best_match_score >= 0.5:
                identity_status = "provisional"
                identity_ref = candidate.best_match_uid
                confidence = candidate.best_match_score
            elif candidate.best_match_uid:
                identity_status = "provisional"
                identity_ref = candidate.best_match_uid
                confidence = candidate.best_match_score

            card = candidate.card
            vp = candidate.voiceprint

            evidence: list[str] = []
            if card and card.source_image_eid:
                evidence.append(card.source_image_eid)
            if vp and vp.source_audio_eid:
                evidence.append(vp.source_audio_eid)

            participants.append(CanonicalParticipant(
                participant_id=f"P{next_id}",
                role="visitor",
                identity_status=identity_status,
                identity_ref=identity_ref,
                identity_confidence=confidence,
                display_name=card.name if card else (vp.uid if vp else ""),
                company=card.company if card else "",
                title=card.title if card else "",
                phone=card.phone if card else "",
                email=card.email if card else "",
                evidence_refs=evidence,
            ))
            next_id += 1

        return participants

    # ── Turns ───────────────────────────────────────────

    def _build_turns(
        self,
        clusters: list[SpeakerCluster],
        card_transcripts: dict[str, list[str]] | None,
    ) -> list[CanonicalTurn]:
        """Build CanonicalTurn list from diarization segments.

        card_transcripts: optional {speaker_cluster_id: [text, ...]}
          where each text entry is per-segment transcription.

        Transcript text is TRUNCATED to 500 chars per turn.
        Full transcript is in Evidence Store via EID reference.
        """
        turns: list[CanonicalTurn] = []
        turn_seq = 0

        for cluster in clusters:
            for seg in cluster.segments:
                # Truncate text to 500 chars — full text in Evidence
                text = (seg.text or "")[:500]

                turns.append(CanonicalTurn(
                    tid=f"turn_{turn_seq:04d}",
                    participant_ref=cluster.cluster_id,
                    text=text,
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                    language="zh",
                    confidence=0.8,  # placeholder ASR confidence
                    source_evidence="",  # EID from diarization
                ))
                turn_seq += 1

        return turns

    # ── Memory Seeds ────────────────────────────────────

    def _build_memory_seeds(
        self, session_id: str, candidates: list[PersonCandidate],
    ) -> list[MemorySeed]:
        """Build MemorySeed per confirmed/provisional visitor.

        NEVER includes transcript text.  Only structured signals from
        business card + voiceprint match.
        """
        seeds: list[MemorySeed] = []

        for candidate in candidates:
            uid = candidate.confirmed_uid or candidate.best_match_uid
            if not uid:
                continue

            card = candidate.card

            seed = MemorySeed(
                uid=uid,
                sid=session_id,
                industry=card.industry_hint if card else "",
                company_name=card.company if card else "",
                person_name=card.name if card else "",
                title=card.title if card else "",
                phone=card.phone if card else "",
                email=card.email if card else "",
                intent_hints=[],  # filled by SLM later
                first_impression="",  # filled by human or SLM
                notes="",
                source_evidence=[],
            )

            if card and card.source_image_eid:
                seed.source_evidence.append(card.source_image_eid)

            seeds.append(seed)

        return seeds

    # ── CRM Seeds ───────────────────────────────────────

    def _build_crm_seeds(
        self, candidates: list[PersonCandidate],
    ) -> list[CRMSeed]:
        """Build CRMSeed — only actionable, CRM-ready data.

        Action: "create" for new contacts, "update" for known contacts.
        No internal analysis objects.
        """
        seeds: list[CRMSeed] = []

        for candidate in candidates:
            uid = candidate.confirmed_uid or candidate.best_match_uid
            card = candidate.card

            # Determine action
            if candidate.is_confirmed or (uid and candidate.best_match_score >= 0.85):
                action = "update"  # existing contact, update from new encounter
            elif card and (card.name or card.company):
                action = "create"  # new contact
            else:
                continue  # no actionable data

            contact_data: dict[str, Any] = {}
            if card:
                if card.name:
                    contact_data["name"] = card.name
                if card.company:
                    contact_data["company"] = card.company
                if card.title:
                    contact_data["title"] = card.title
                if card.phone:
                    contact_data["phone"] = card.phone
                if card.email:
                    contact_data["email"] = card.email
                if card.industry_hint:
                    contact_data["industry"] = card.industry_hint

            if uid:
                contact_data["uid"] = uid

            seeds.append(CRMSeed(
                action=action,
                uid=uid or f"new_{uuid4().hex[:8]}",
                contact_data=contact_data,
                notes=f"Expo intake — {card.name if card else 'unknown'} at {card.company if card else 'unknown'} — {action}",
                source="expo_intake",
                evidence_refs=[card.source_image_eid] if card and card.source_image_eid else [],
            ))

        return seeds

    # ── Audit Entries ───────────────────────────────────

    def _build_audit_entries(
        self,
        session_id: str,
        candidates: list[PersonCandidate],
        clusters: list[SpeakerCluster],
    ) -> list[AuditEntry]:
        """Build AuditEntry for the session and identity resolution events."""
        entries: list[AuditEntry] = []

        # Session creation audit
        entries.append(AuditEntry(
            audit_id=f"audit_{uuid4().hex[:8]}",
            event_type="session_created",
            event_id=session_id,
            payload={
                "participant_count": len(candidates),
                "cluster_count": len(clusters),
            },
            requires_review=any(c.requires_review for c in candidates),
        ))

        # Identity resolution audit per candidate
        for candidate in candidates:
            decision = "auto_match"
            if candidate.requires_review:
                decision = "ambiguous"
            if not candidate.best_match_uid:
                decision = "no_match"
            if candidate.review_reason == "card_voice_mismatch":
                decision = "conflict"

            entries.append(AuditEntry(
                audit_id=f"audit_{uuid4().hex[:8]}",
                event_type="identity_resolved",
                event_id=candidate.person_id,
                payload={
                    "source": candidate.source,
                    "best_match_uid": candidate.best_match_uid or "",
                    "best_match_score": candidate.best_match_score,
                    "is_confirmed": candidate.is_confirmed,
                },
                decision_type=decision,
                requires_review=candidate.requires_review,
            ))

        return entries

    # ── Helpers ─────────────────────────────────────────

    @staticmethod
    def _calc_duration(turns: list[CanonicalTurn]) -> int:
        if not turns:
            return 0
        return max(t.end_ms for t in turns) - min(t.start_ms for t in turns)

    @staticmethod
    def _collect_evidence(
        candidates: list[PersonCandidate],
        clusters: list[SpeakerCluster],
    ) -> list[str]:
        eids: list[str] = []
        for c in candidates:
            if c.card and c.card.source_image_eid:
                eids.append(c.card.source_image_eid)
            if c.voiceprint and c.voiceprint.source_audio_eid:
                eids.append(c.voiceprint.source_audio_eid)
        return eids
