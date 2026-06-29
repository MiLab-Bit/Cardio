# tests/intake/test_assembly.py
"""Canonical Session Assembler tests."""

import pytest

from byou.intake.assembly import CanonicalSessionAssembler
from byou.intake.models import (
    BusinessCard,
    PersonCandidate,
    SpeakerCluster,
    SpeakerSegment,
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


# ══════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════

def _make_card(name="张三", company="腾讯", phone="13800138000", **kwargs):
    return BusinessCard(name=name, company=company, phone=phone, **kwargs)


def _make_cluster(cluster_id="spk_01", text_segments=None):
    segments = text_segments or [("你好", 0, 5000)]
    return SpeakerCluster(
        cluster_id=cluster_id,
        segments=[
            SpeakerSegment(start_ms=s, end_ms=e, text=t)
            for t, s, e in segments
        ],
    )


# ══════════════════════════════════════════════════════════
# Basic assembly
# ══════════════════════════════════════════════════════════

class TestBasicAssembly:
    def test_empty_input(self):
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[],
            speaker_clusters=[],
            bd_staff_ids=[],
        )
        assert isinstance(result["session"], CanonicalSession)
        assert result["session"].sid == "sid_001"
        assert result["session"].participants == []
        assert result["session"].turns == []
        assert result["memory_seeds"] == []
        assert result["crm_seeds"] == []
        assert len(result["audit_entries"]) == 1  # always session_created
        assert not result["review_required"]

    def test_bd_staff_participants(self):
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            bd_staff_ids=["bid_staff_01", "bid_staff_02"],
        )
        participants = result["session"].participants
        assert len(participants) == 2
        assert participants[0].role == "bd_staff"
        assert participants[0].identity_status == "confirmed"
        assert participants[0].identity_ref == "bid_staff_01"


# ══════════════════════════════════════════════════════════
# Participant identity status
# ══════════════════════════════════════════════════════════

class TestParticipantIdentity:
    def test_confirmed_identity(self):
        card = _make_card("张三", "腾讯")
        pc = PersonCandidate(
            source="card",
            card=card,
            is_confirmed=True,
            confirmed_uid="uid_001",
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        p = result["session"].participants[0]
        assert p.identity_status == "confirmed"
        assert p.identity_ref == "uid_001"
        assert p.identity_confidence == 1.0
        assert p.display_name == "张三"
        assert p.company == "腾讯"

    def test_auto_match_high_confidence(self):
        card = _make_card("张三", "腾讯")
        pc = PersonCandidate(
            source="card",
            card=card,
            best_match_uid="uid_001",
            best_match_score=0.92,
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        p = result["session"].participants[0]
        assert p.identity_status == "confirmed"
        assert p.identity_confidence == 0.92

    def test_provisional_match(self):
        card = _make_card("张三", "腾讯")
        pc = PersonCandidate(
            source="card",
            card=card,
            best_match_uid="uid_001",
            best_match_score=0.65,
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        p = result["session"].participants[0]
        assert p.identity_status == "provisional"
        assert p.identity_confidence == 0.65

    def test_unknown_identity(self):
        pc = PersonCandidate(source="card")
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        p = result["session"].participants[0]
        assert p.identity_status == "unknown"


# ══════════════════════════════════════════════════════════
# Turn assembly
# ══════════════════════════════════════════════════════════

class TestTurnAssembly:
    def test_single_cluster_single_segment(self):
        cluster = _make_cluster("spk_01", [("你好，我想了解一下产品", 0, 5000)])
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            speaker_clusters=[cluster],
        )
        turns = result["session"].turns
        assert len(turns) == 1
        assert turns[0].text == "你好，我想了解一下产品"
        assert turns[0].participant_ref == "spk_01"

    def test_transcript_truncated(self):
        long_text = "x" * 800
        cluster = _make_cluster("spk_01", [(long_text, 0, 1000)])
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            speaker_clusters=[cluster],
        )
        assert len(result["session"].turns[0].text) <= 500

    def test_multiple_segments(self):
        cluster = _make_cluster("spk_01", [
            ("hello", 0, 3000),
            ("world", 4000, 7000),
        ])
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            speaker_clusters=[cluster],
        )
        assert len(result["session"].turns) == 2


# ══════════════════════════════════════════════════════════
# Memory Seed — transcript boundary
# ══════════════════════════════════════════════════════════

class TestMemorySeedBoundary:
    def test_no_transcript_in_memory_seed(self):
        card = _make_card("张三", "腾讯")
        pc = PersonCandidate(
            source="card",
            card=card,
            confirmed_uid="uid_001",
            is_confirmed=True,
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
            speaker_clusters=[_make_cluster("spk_01")],  # turns exist
        )
        seeds = result["memory_seeds"]
        assert len(seeds) == 1
        seed = seeds[0]
        seed_dict = seed.model_dump()
        assert "transcript" not in seed_dict
        assert "transcript_text" not in seed_dict
        assert "turns" not in seed_dict
        # Only structured data
        assert seed.company_name == "腾讯"
        assert seed.person_name == "张三"

    def test_memory_seed_only_for_confirmed_or_matched(self):
        """Only confirmed/provisional identities get MemorySeeds."""
        pc = PersonCandidate(source="card")  # no UID match
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        assert result["memory_seeds"] == []

    def test_memory_seed_entry_for_high_score_match(self):
        card = _make_card("张三")
        pc = PersonCandidate(
            source="card", card=card,
            best_match_uid="uid_001", best_match_score=0.9,
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        assert len(result["memory_seeds"]) == 1


# ══════════════════════════════════════════════════════════
# CRM Seed
# ══════════════════════════════════════════════════════════

class TestCRMSeed:
    def test_create_seed_for_new_contact(self):
        card = _make_card("张三", "腾讯", phone="13800138000")
        pc = PersonCandidate(source="card", card=card)
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        seeds = result["crm_seeds"]
        assert len(seeds) == 1
        assert seeds[0].action == "create"
        assert seeds[0].contact_data["name"] == "张三"

    def test_update_seed_for_confirmed(self):
        card = _make_card("张三", "腾讯")
        pc = PersonCandidate(
            source="card", card=card,
            is_confirmed=True, confirmed_uid="uid_001",
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        seeds = result["crm_seeds"]
        assert len(seeds) == 1
        assert seeds[0].action == "update"

    def test_no_crm_for_empty_candidate(self):
        pc = PersonCandidate(source="card")  # no card data, no uid
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        assert result["crm_seeds"] == []


# ══════════════════════════════════════════════════════════
# Audit Entries
# ══════════════════════════════════════════════════════════

class TestAuditEntries:
    def test_session_created_audit_always(self):
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(session_id="sid_001")
        entries = result["audit_entries"]
        session_audits = [e for e in entries if e.event_type == "session_created"]
        assert len(session_audits) == 1

    def test_identity_audit_per_candidate(self):
        card = _make_card("张三")
        pc1 = PersonCandidate(
            source="card", card=card,
            best_match_uid="uid_001", best_match_score=0.9,
        )
        pc2 = PersonCandidate(
            source="card",
            requires_review=True, review_reason="no_match",
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc1, pc2],
        )
        identity_audits = [
            e for e in result["audit_entries"]
            if e.event_type == "identity_resolved"
        ]
        assert len(identity_audits) == 2

    def test_auto_match_decision_type(self):
        card = _make_card("张三")
        pc = PersonCandidate(
            source="card", card=card,
            best_match_uid="uid_001", best_match_score=0.95,
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        identity_audit = [
            e for e in result["audit_entries"]
            if e.event_type == "identity_resolved"
        ][0]
        assert identity_audit.decision_type == "auto_match"

    def test_conflict_decision_type(self):
        card = _make_card("张三")
        pc = PersonCandidate(
            source="card+voiceprint", card=card,
            requires_review=True,
            review_reason="card_voice_mismatch",
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        identity_audit = [
            e for e in result["audit_entries"]
            if e.event_type == "identity_resolved"
        ][0]
        assert identity_audit.decision_type == "conflict"


# ══════════════════════════════════════════════════════════
# Review required
# ══════════════════════════════════════════════════════════

class TestReviewRequired:
    def test_no_review_when_all_auto_matched(self):
        pc = PersonCandidate(
            source="card",
            best_match_uid="uid_001",
            best_match_score=0.95,
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        assert not result["review_required"]

    def test_review_when_any_ambiguous(self):
        pc = PersonCandidate(
            source="card", requires_review=True,
            review_reason="no_match",
        )
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        assert result["review_required"]


# ══════════════════════════════════════════════════════════
# Graceful degradation
# ══════════════════════════════════════════════════════════

class TestGracefulDegradation:
    def test_no_cards(self):
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[],
            speaker_clusters=[_make_cluster("spk_01")],
        )
        assert isinstance(result["session"], CanonicalSession)
        assert result["memory_seeds"] == []
        assert result["crm_seeds"] == []

    def test_no_voiceprints(self):
        card = _make_card("张三")
        pc = PersonCandidate(source="card", card=card)
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            person_candidates=[pc],
        )
        assert len(result["memory_seeds"]) == 0  # no UID

    def test_single_speaker(self):
        """Single speaker → no diarization ambiguity."""
        cluster = _make_cluster("spk_only")
        assembler = CanonicalSessionAssembler()
        result = assembler.assemble(
            session_id="sid_001",
            speaker_clusters=[cluster],
        )
        assert len(result["session"].turns) == 1
