# byou/intake/diarization/normalizer.py
"""Diarization normalizer — clean pyannote/ASR output → SpeakerCluster-compatible dicts.

Handles:
  - Timestamp normalization (ms values)
  - Text cleaning (ASR artifacts)
  - Segment deduplication
  - Speaker label unification
"""

from __future__ import annotations

import re
from typing import Any


class DiarizationNormalizer:
    """Normalize raw diarization/ASR segments → clean SpeakerCluster dicts."""

    # Common ASR artifacts to strip
    _ASR_ARTIFACTS = [
        (r"\[.*?\]", ""),     # [unclear], [silence]
        (r"\(.*?\)", ""),     # (unclear)
        (r"<.*?>", ""),        # <noise>
        (r"\*{2,}", ""),       # ***
        (r"…+", "..."),        # …… → ...
    ]

    def normalize_segment(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single speaker segment dict → clean dict."""
        return {
            "start_ms": self._to_ms(raw.get("start", 0) or raw.get("start_ms", 0)),
            "end_ms": self._to_ms(raw.get("end", 0) or raw.get("end_ms", 0)),
            "text": self._clean_asr_text(raw.get("text", "")),
        }

    def normalize_cluster(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single speaker cluster dict → clean dict."""
        raw_segments = raw.get("segments") or raw.get("turns") or []
        segments = [
            self.normalize_segment(s) for s in raw_segments
            if isinstance(s, dict)
        ]

        # Deduplicate by text (common ASR artifact: duplicate output)
        segments = self._dedup_segments(segments)

        embedding = list(raw.get("embedding") or raw.get("vector") or [])

        result: dict[str, Any] = {
            "cluster_id": str(
                raw.get("cluster_id")
                or raw.get("speaker")
                or raw.get("label")
                or ""
            ),
            "embedding": [float(v) for v in embedding] if embedding else [],
            "segments": segments,
        }

        # is_registered: None = unknown, True/False = known
        reg = raw.get("is_registered")
        if reg is not None:
            result["is_registered"] = bool(reg)

        return result

    def normalize_batch(self, raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.normalize_cluster(r) for r in raws]

    # ── Internal ────────────────────────────────────────

    @staticmethod
    def _to_ms(value: Any) -> int:
        """Convert seconds or milliseconds to ms."""
        if isinstance(value, (int, float)):
            # If value < 1000, assume it's in seconds
            if value < 1000:
                return int(value * 1000)
            return int(value)
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return 0

    @classmethod
    def _clean_asr_text(cls, text: Any) -> str:
        """Clean ASR output — remove artifacts, normalize whitespace."""
        text = str(text or "")
        for pattern, replacement in cls._ASR_ARTIFACTS:
            text = re.sub(pattern, replacement, text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _dedup_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicate consecutive segments with identical text."""
        if not segments:
            return segments

        result = [segments[0]]
        for seg in segments[1:]:
            prev = result[-1]
            if seg.get("text") == prev.get("text") and seg.get("start_ms") == prev.get("start_ms"):
                continue
            result.append(seg)
        return result
