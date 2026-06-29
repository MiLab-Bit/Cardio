# tests/intake/test_models.py
"""Intake model validation tests."""

import pytest

from byou.intake.models import (
    BusinessCard,
    EID,
    EvidenceType,
    IntakeProcessingResult,
    PersonCandidate,
    RawIntakePackage,
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
# EID
# ══════════════════════════════════════════════════════════

class TestEID:
    def test_create_card_evidence(self):
        eid = EID(evidence_type=EvidenceType.CARD_IMAGE, source="camera_1.jpg")
        assert eid.eid.startswith("eid_")
        assert eid.evidence_type == EvidenceType.CARD_IMAGE
        assert eid.source == "camera_1.jpg"

    def test_auto_generated_eid(self):
        eid1 = EID(evidence_type=EvidenceType.AUDIO_CLIP)
        eid2 = EID(evidence_type=EvidenceType.AUDIO_CLIP)
        assert eid1.eid != eid2.eid


# ══════════════════════════════════════════════════════════
# BusinessCard
# ══════════════════════════════════════════════════════════

class TestBusinessCard:
    def test_full_card(self):
        card = BusinessCard(
            name="张三",
            company="腾讯科技",
            title="技术总监",
            phone="13800138000",
            email="zhangsan@tencent.com",
            industry_hint="互联网",
        )
        assert card.name == "张三"
        assert card.company == "腾讯科技"
        assert card.phone == "13800138000"

    def test_minimal_card(self):
        card = BusinessCard()
        assert card.name == ""
        assert card.company == ""

    def test_confidence_defaults(self):
        card = BusinessCard(name="test")
        assert card.ocr_confidence == 0.0
        assert card.ner_confidence == 0.0


# ══════════════════════════════════════════════════════════
# VoiceprintProfile
# ══════════════════════════════════════════════════════════

class TestVoiceprintProfile:
    def test_full_profile(self):
        vp = VoiceprintProfile(
            uid="uid_001",
            embedding=[0.1, 0.2, 0.3],
            source_audio_eid="eid_001",
        )
        assert vp.uid == "uid_001"
        assert vp.embedding == [0.1, 0.2, 0.3]
        assert vp.is_active

    def test_empty_embedding(self):
        vp = VoiceprintProfile()
        assert vp.embedding == []
        assert vp.uid == ""


# ══════════════════════════════════════════════════════════
# PersonCandidate
# ══════════════════════════════════════════════════════════

class TestPersonCandidate:
    def test_card_only(self):
        card = BusinessCard(name="张三", company="腾讯")
        pc = PersonCandidate(source="card", card=card)
        assert pc.source == "card"
        assert pc.card.name == "张三"

    def test_voiceprint_only(self):
        vp = VoiceprintProfile(uid="uid_001")
        pc = PersonCandidate(source="voiceprint", voiceprint=vp)
        assert pc.source == "voiceprint"
        assert pc.voiceprint.uid == "uid_001"

    def test_confirmed_flag(self):
        pc = PersonCandidate(
            source="card+voiceprint",
            is_confirmed=True,
            confirmed_uid="uid_001",
        )
        assert pc.is_confirmed
        assert pc.confirmed_uid == "uid_001"

    def test_requires_review_on_low_score(self):
        pc = PersonCandidate(
            best_match_score=0.3,
            requires_review=True,
            review_reason="low confidence",
        )
        assert pc.requires_review
        assert pc.review_reason == "low confidence"


# ══════════════════════════════════════════════════════════
# SpeakerCluster / Segment
# ══════════════════════════════════════════════════════════

class TestSpeakerCluster:
    def test_cluster_with_segments(self):
        segs = [
            SpeakerSegment(start_ms=0, end_ms=5000, text="你好"),
            SpeakerSegment(start_ms=6000, end_ms=10000, text="再见"),
        ]
        cluster = SpeakerCluster(
            cluster_id="spk_01",
            embedding=[0.1, 0.2],
            segments=segs,
            is_registered=True,
        )
        assert cluster.cluster_id == "spk_01"
        assert len(cluster.segments) == 2
        assert cluster.is_registered is True

    def test_unknown_registration(self):
        cluster = SpeakerCluster(cluster_id="spk_unknown")
        assert cluster.is_registered is None


# ══════════════════════════════════════════════════════════
# RawIntakePackage
# ══════════════════════════════════════════════════════════

class TestRawIntakePackage:
    def test_minimal_package(self):
        pkg = RawIntakePackage()
        assert pkg.session_id.startswith("sid_expo_")

    def test_full_package(self):
        card = BusinessCard(name="test")
        vp = VoiceprintProfile()
        seg = SpeakerSegment(start_ms=0, end_ms=100, text="hi")
        cluster = SpeakerCluster(cluster_id="spk_0", segments=[seg])
        pkg = RawIntakePackage(
            session_id="sid_001",
            cards=[card],
            voiceprints=[vp],
            speaker_clusters=[cluster],
            venue={"booth": "B12", "event": "TechExpo2026"},
            bd_staff_ids=["bid_staff_01"],
        )
        assert pkg.session_id == "sid_001"
        assert len(pkg.cards) == 1
        assert pkg.venue["booth"] == "B12"

    def test_empty_lists_ok(self):
        pkg = RawIntakePackage()
        assert pkg.cards == []
        assert pkg.voiceprints == []
        assert pkg.speaker_clusters == []


# ══════════════════════════════════════════════════════════
# Canonical models (channel_contract) presence check
# ══════════════════════════════════════════════════════════

class TestCanonicalModelsExist:
    def test_canonical_session_fields(self):
        s = CanonicalSession(sid="sid_001")
        assert s.sid == "sid_001"
        assert s.participants == []
        assert s.turns == []

    def test_canonical_turn_field_types(self):
        t = CanonicalTurn(
            tid="turn_0001",
            participant_ref="P0",
            text="test text",
            start_ms=100,
            end_ms=500,
        )
        assert t.tid == "turn_0001"
        assert len(t.text) <= 500

    def test_canonical_participant_identity_states(self):
        # unknown
        p1 = CanonicalParticipant(participant_id="P0")
        assert p1.identity_status == "unknown"

        # confirmed
        p2 = CanonicalParticipant(
            participant_id="P1",
            identity_status="confirmed",
            identity_ref="uid_001",
            identity_confidence=1.0,
        )
        assert p2.identity_status == "confirmed"

        # provisinal
        p3 = CanonicalParticipant(
            participant_id="P2",
            identity_status="provisional",
            identity_ref="uid_002",
            identity_confidence=0.7,
        )
        assert p3.identity_status == "provisional"

    def test_memory_seed_no_transcript(self):
        seed = MemorySeed(uid="uid_001", sid="sid_001")
        d = seed.model_dump()
        # Must NOT have transcript_text field
        assert "transcript_text" not in d
        assert "transcript" not in d

    def test_crm_seed_only_actionable(self):
        seed = CRMSeed(
            uid="uid_001",
            contact_data={"name": "张三", "company": "腾讯"},
            notes="展会交流",
        )
        d = seed.model_dump()
        assert "transcript" not in d
        assert "internal_analysis" not in d
        assert d["contact_data"]["name"] == "张三"

    def test_audit_entry_immutable_feel(self):
        entry = AuditEntry(
            audit_id="audit_001",
            event_type="session_created",
            event_id="sid_001",
        )
        assert entry.event_type == "session_created"


# ══════════════════════════════════════════════════════════
# IntakeProcessingResult
# ══════════════════════════════════════════════════════════

class TestIntakeProcessingResult:
    def test_success_result(self):
        result = IntakeProcessingResult(
            session_id="sid_001",
            canonical_session={"sid": "sid_001"},
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[],
            review_required=False,
            review_flags=[],
            errors=[],
        )
        assert result.session_id == "sid_001"
        assert not result.review_required

    def test_error_result(self):
        result = IntakeProcessingResult(
            session_id="sid_002",
            canonical_session={},
            memory_seeds=[],
            crm_seeds=[],
            audit_entries=[],
            review_required=True,
            review_flags=["rev_001"],
            errors=["Memory publish failed"],
        )
        assert result.review_required
        assert len(result.errors) == 1
