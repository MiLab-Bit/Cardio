# byou/intake/voiceprint/adapter.py
"""Voiceprint adapter — WeSpeaker raw embedding → VoiceprintProfile.

Handles WeSpeaker and equivalent speaker embedding outputs.
Provider payload (WeSpeaker x-vector, enrollment metadata) NEVER leaks out.
Only VoiceprintProfile exits to extraction layer.

Input shapes supported:
  1. {embedding: [float, ...], uid, source_audio_eid, metadata}
  2. {speaker_id, vector: [float, ...], audio_path, ...}  (WeSpeaker format)
  3. {enrollments: [{...}], matches: [{...}]}  (bulk mode)
"""

from __future__ import annotations

import logging
from typing import Any

from byou.intake.models import VoiceprintProfile

logger = logging.getLogger(__name__)


class VoiceprintAdapter:
    """Convert voiceprint provider output → VoiceprintProfile.

    Usage:
        adapter = VoiceprintAdapter()
        vp = adapter.process(raw_wespeaker_result)
    """

    def process(self, raw: dict[str, Any]) -> VoiceprintProfile:
        """Normalize raw voiceprint provider output → VoiceprintProfile.

        Returns VoiceprintProfile with embedding, uid, and source reference.
        """
        # Extract embedding — handle multiple provider formats
        embedding = self._extract_embedding(raw)

        # Extract UID (may be empty for new enrollments)
        uid = str(raw.get("uid") or raw.get("speaker_id") or "")

        # Extract source evidence reference
        source_eid = str(
            raw.get("source_audio_eid")
            or raw.get("audio_path")
            or raw.get("source")
            or ""
        )

        # Extract metadata (provider-specific, will be stripped before Core)
        metadata: dict[str, Any] = {}
        if "metadata" in raw and isinstance(raw["metadata"], dict):
            metadata = raw["metadata"]
        else:
            # Collect common WeSpeaker fields as metadata
            for key in ("model_id", "model_version", "quality_score", "duration_ms"):
                if key in raw:
                    metadata[key] = raw[key]

        return VoiceprintProfile(
            uid=uid,
            embedding=embedding,
            source_audio_eid=source_eid,
            metadata=metadata,
        )

    def process_batch(self, raws: list[dict[str, Any]]) -> list[VoiceprintProfile]:
        return [self.process(r) for r in raws]

    def process_enrollment(
        self, raw: dict[str, Any], uid: str = "", source_audio_eid: str = ""
    ) -> VoiceprintProfile:
        """Convenience: process an enrollment event."""
        raw = dict(raw)
        raw.setdefault("uid", uid)
        raw.setdefault("source_audio_eid", source_audio_eid)
        return self.process(raw)

    # ── Internal ────────────────────────────────────────

    @staticmethod
    def _extract_embedding(raw: dict[str, Any]) -> list[float]:
        """Extract embedding vector from multiple provider formats.

        WeSpeaker: raw["vector"] or raw["embedding"]
        Legacy: raw["x_vector"] or raw["feature"]
        """
        for key in ("embedding", "vector", "x_vector", "feature"):
            val = raw.get(key)
            if val and isinstance(val, list) and len(val) > 0:
                return [float(v) for v in val]

        return []
