# byou/intake/__init__.py
"""Intake & Identity Resolution — Phase 3 v2.

Turns raw expo inputs (business cards, voiceprints, recordings) into
canonical sessions and seeds for Byou Core.

Layers:
  1. card/          — PaddleOCR → BusinessCard adapter
  2. voiceprint/    — WeSpeaker → VoiceprintProfile adapter + matcher
  3. diarization/   — pyannote/ASR → SpeakerCluster adapter
  4. extraction.py  — orchestration: calls adapters + matches identities
  5. assembly.py    — intake models → CanonicalSession + Seeds
  6. publisher.py   — Seeds → Memory/CRM/Audit/Review gateways
  7. handler.py     — main entry: raw → extract → assemble → publish
"""

from byou.intake.card.adapter import CardAdapter
from byou.intake.card.normalizer import CardFieldNormalizer
from byou.intake.diarization.adapter import DiarizationAdapter
from byou.intake.diarization.normalizer import DiarizationNormalizer
from byou.intake.extraction import ExtractionOrchestrator, IdentityMatcher
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
from byou.intake.voiceprint.adapter import VoiceprintAdapter
from byou.intake.voiceprint.matcher import MatchDecision, MatchResult, VoiceprintMatcher

__all__ = [
    # Models
    "BusinessCard",
    "EID",
    "EvidenceType",
    "IntakeProcessingResult",
    "PersonCandidate",
    "RawIntakePackage",
    "SpeakerCluster",
    "SpeakerSegment",
    "VoiceprintProfile",
    # Card
    "CardAdapter",
    "CardFieldNormalizer",
    # Voiceprint
    "VoiceprintAdapter",
    "VoiceprintMatcher",
    "MatchDecision",
    "MatchResult",
    # Diarization
    "DiarizationAdapter",
    "DiarizationNormalizer",
    # Orchestration
    "ExtractionOrchestrator",
    "IdentityMatcher",
]
