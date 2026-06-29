# byou/intake/diarization/__init__.py
"""Diarization intake adapter — pyannote/ASR output → SpeakerCluster[].

Provider payload stays here.  Only SpeakerCluster[] exit to extraction layer.
"""

from byou.intake.diarization.adapter import DiarizationAdapter
from byou.intake.diarization.normalizer import DiarizationNormalizer

__all__ = ["DiarizationAdapter", "DiarizationNormalizer"]
