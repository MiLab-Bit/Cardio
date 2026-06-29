# byou/intake/models.py
"""Expo-specific intake models — EID, VPID, BusinessCard, etc.

These models are expo-specific and do NOT belong in channel_contract.py.
They describe raw intake artifacts before normalization to canonical types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# Evidence ID — the root of provenance
# ══════════════════════════════════════════════════════════

class EvidenceType(str, Enum):
    CARD_IMAGE = "card_image"
    AUDIO_CLIP = "audio_clip"
    OCR_RESULT = "ocr_result"
    ASR_RESULT = "asr_result"
    DIARIZATION_RESULT = "diarization_result"
    VOICEPRINT_ENROLLMENT = "voiceprint_enrollment"
    MANUAL_INPUT = "manual_input"


class EID(BaseModel):
    """Evidence ID — a unit of raw evidence with provenance.

    Every piece of data entering Byou gets an EID.
    30-day retention.  Reprocessable.
    """
    eid: str = Field(default_factory=lambda: f"eid_{uuid4().hex[:12]}")
    evidence_type: EvidenceType
    source: str = ""  # file path / device id
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_meta: dict[str, Any] = Field(default_factory=dict)  # provider-specific, strippable


# ══════════════════════════════════════════════════════════
# Business Card
# ══════════════════════════════════════════════════════════

class BusinessCard(BaseModel):
    """Parsed business card — output of OCR + NER extraction."""
    card_id: str = Field(default_factory=lambda: f"card_{uuid4().hex[:8]}")
    raw_text: str = ""
    name: str = ""
    company: str = ""
    title: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    industry_hint: str = ""  # derived from company name / business scope

    # OCR confidence
    ocr_confidence: float = 0.0
    ner_confidence: float = 0.0

    # Evidence
    source_image_eid: str = ""
    source_ocr_eid: str = ""


# ══════════════════════════════════════════════════════════
# Voiceprint
# ══════════════════════════════════════════════════════════

class VoiceprintProfile(BaseModel):
    """A registered voiceprint — permanent, versioned."""
    vpid: str = Field(default_factory=lambda: f"vpid_{uuid4().hex[:8]}")
    uid: str = ""  # linked UID (may be empty if not yet matched)
    embedding: list[float] = Field(default_factory=list)
    source_audio_eid: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════
# PersonCandidate (temporary, → UID on confirm)
# ══════════════════════════════════════════════════════════

class PersonCandidate(BaseModel):
    """A provisional person identity — NOT yet confirmed as a UID.

    Upgraded to UID after human confirmation or auto_match ≥ 0.85.
    Before confirmation, stays in review queue.
    """
    person_id: str = Field(default_factory=lambda: f"pc_{uuid4().hex[:8]}")
    source: str = "card"  # "card" | "voiceprint" | "card+voiceprint"

    # From business card
    card: BusinessCard | None = None

    # From voiceprint
    voiceprint: VoiceprintProfile | None = None

    # Matching result
    best_match_uid: str | None = None
    best_match_score: float = 0.0
    match_candidates: list[dict[str, Any]] = Field(default_factory=list)
    # [{uid, score, evidence}]

    # Lifecycle
    is_confirmed: bool = False
    confirmed_uid: str | None = None
    requires_review: bool = False
    review_reason: str = ""


# ══════════════════════════════════════════════════════════
# Speaker cluster (from diarization)
# ══════════════════════════════════════════════════════════

class SpeakerSegment(BaseModel):
    """A time segment assigned to a speaker cluster."""
    start_ms: int
    end_ms: int
    text: str = ""  # ASR text for this segment


class SpeakerCluster(BaseModel):
    """A speaker cluster from diarization — temporary, consumed during matching."""
    cluster_id: str
    embedding: list[float] = Field(default_factory=list)
    segments: list[SpeakerSegment] = Field(default_factory=list)
    is_registered: bool | None = None  # None = unknown


# ══════════════════════════════════════════════════════════
# Intake input package
# ══════════════════════════════════════════════════════════

class RawIntakePackage(BaseModel):
    """Raw input for Intake processing.

    This is the entry point — what comes in from the expo floor.
    All fields are optional; the system gracefully degrades.
    """
    session_id: str = Field(default_factory=lambda: f"sid_expo_{uuid4().hex[:8]}")

    # Business cards (may be empty)
    cards: list[BusinessCard] = Field(default_factory=list)

    # Voiceprint enrollment (may be empty)
    voiceprints: list[VoiceprintProfile] = Field(default_factory=list)

    # Audio files for voiceprint extraction (may be empty)
    audio_paths: list[str] = Field(default_factory=list)

    # Speaker clusters from diarization (may be empty)
    speaker_clusters: list[SpeakerCluster] = Field(default_factory=list)

    # Metadata
    venue: dict[str, str] = Field(default_factory=dict)
    bd_staff_ids: list[str] = Field(default_factory=list)  # BIDs of BD staff present
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ══════════════════════════════════════════════════════════
# Intake processing result
# ══════════════════════════════════════════════════════════

class IntakeProcessingResult(BaseModel):
    """Result of a complete Intake processing run."""
    session_id: str
    canonical_session: dict[str, Any] = Field(default_factory=dict)
    memory_seeds: list[dict[str, Any]] = Field(default_factory=list)
    crm_seeds: list[dict[str, Any]] = Field(default_factory=list)
    audit_entries: list[dict[str, Any]] = Field(default_factory=list)
    review_required: bool = False
    review_flags: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
