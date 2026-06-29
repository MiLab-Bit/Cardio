# byou/intake/diarization/adapter.py
"""Diarization adapter — pyannote/ASR raw output → SpeakerCluster[].

Handles:
  1. pyannote.audio Pipeline output (diarization + transcription)
  2. Generic ASR with speaker labels (whisper, aliyun-asr, etc.)
  3. Pre-segmented output (already have speaker labels)

Provider payload (pyannote Annotation, speaker embeddings) NEVER leaks out.
Only SpeakerCluster[] exits to extraction layer.

Input shapes supported:
  1. {speakers: [{speaker, segments: [{start, end, text}], embedding: [...]}]}
  2. {diarization: {...}, transcription: {...}, embeddings: {...}}
  3. {clusters: [{...}]}  (already clustered)
  4. [{speaker: "SPK1", start: 0, end: 2.5, text: "hello"}, ...]  (flat segments)
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.diarization.normalizer import DiarizationNormalizer
from byou.intake.models import SpeakerCluster, SpeakerSegment

logger = logging.getLogger(__name__)


class DiarizationAdapter:
    """Convert diarization provider output → SpeakerCluster[].

    Usage:
        adapter = DiarizationAdapter()
        clusters = adapter.process(raw_pyannote_output)
    """

    def __init__(self):
        self._normalizer = DiarizationNormalizer()

    # ── Main entry ─────────────────────────────────────

    def process(self, raw: dict[str, Any] | list[dict[str, Any]]) -> list[SpeakerCluster]:
        """Main entry: raw provider output → SpeakerCluster[].

        Detects input shape and delegates to appropriate parser.
        """
        # Flat segment list (common ASR output)
        if isinstance(raw, list):
            return self._from_flat_segments(raw)

        # dict with speakers/clusters key
        if "speakers" in raw:
            return self._from_speakers(raw["speakers"])
        if "clusters" in raw:
            return self._from_clusters(raw["clusters"])

        # pyannote Pipeline output format: diarization + transcription
        if "diarization" in raw or "segments" in raw:
            return self._from_speakers(raw.get("speakers", raw.get("segments", [])))

        # Single cluster
        if "speaker" in raw or "cluster_id" in raw:
            return self._from_clusters([raw])

        return []

    def process_batch(self, raws: list[dict[str, Any]]) -> list[SpeakerCluster]:
        """Process multiple raw results (union mode)."""
        all_clusters: list[SpeakerCluster] = []
        for r in raws:
            all_clusters.extend(self.process(r))
        return all_clusters

    # ── Parsers ────────────────────────────────────────

    def _from_speakers(self, speakers: list[dict[str, Any]]) -> list[SpeakerCluster]:
        """Parse speaker-clustered diarization output.

        Input: [{speaker: "SPK_01", segments: [...], embedding: [...]}, ...]
        """
        clusters: list[SpeakerCluster] = []
        for spk in speakers:
            cleaned = self._normalizer.normalize_cluster(spk)
            segs = self._build_segments(cleaned.get("segments", []))
            clusters.append(SpeakerCluster(
                cluster_id=cleaned["cluster_id"],
                embedding=cleaned.get("embedding", []),
                segments=segs,
                is_registered=cleaned.get("is_registered"),
            ))
        return clusters

    def _from_clusters(self, clusters: list[dict[str, Any]]) -> list[SpeakerCluster]:
        """Parse pre-clustered diarization output."""
        return self._from_speakers(clusters)

    def _from_flat_segments(self, segments: list[dict[str, Any]]) -> list[SpeakerCluster]:
        """Parse flat segment list (no speaker clustering provided).

        Groups by speaker label.  Each unique speaker → one cluster.
        """
        from collections import defaultdict
        by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for seg in segments:
            speaker = str(seg.get("speaker") or seg.get("speaker_id") or "SPK_UNKNOWN")
            by_speaker[speaker].append(seg)

        clusters: list[SpeakerCluster] = []
        for speaker, segs in by_speaker.items():
            cleaned_segs = [self._normalizer.normalize_segment(s) for s in segs]
            built = self._build_segments(cleaned_segs)
            clusters.append(SpeakerCluster(
                cluster_id=speaker,
                embedding=[],
                segments=built,
                is_registered=None,
            ))
        return clusters

    # ── Helpers ─────────────────────────────────────────

    @staticmethod
    def _build_segments(normalized: list[dict[str, Any]]) -> list[SpeakerSegment]:
        return [
            SpeakerSegment(
                start_ms=s["start_ms"],
                end_ms=s["end_ms"],
                text=s["text"],
            )
            for s in normalized
            if s["end_ms"] > s["start_ms"]
        ]
