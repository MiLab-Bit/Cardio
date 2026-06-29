# byou/intake/voiceprint/__init__.py
"""Voiceprint intake — extract, adapt, match.

Pipeline:
    audio → VoiceprintExtractor → embedding → VoiceprintAdapter → VoiceprintProfile
                                              → VoiceprintMatcher → MatchResult

Provider payload stays here.  Only VoiceprintProfile + match dict exit.
"""

from byou.intake.voiceprint.adapter import VoiceprintAdapter
from byou.intake.voiceprint.extractor import (
    MockVoiceprintExtractor,
    VoiceprintExtractor,
)
from byou.intake.voiceprint.matcher import VoiceprintMatcher

__all__ = [
    "VoiceprintExtractor",
    "MockVoiceprintExtractor",
    "VoiceprintAdapter",
    "VoiceprintMatcher",
]
