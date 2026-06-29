# tests/intake/test_diarization_adapter.py
"""Diarization adapter + normalizer tests — pyannote/ASR → SpeakerCluster[]."""

import pytest

from byou.intake.diarization.adapter import DiarizationAdapter
from byou.intake.diarization.normalizer import DiarizationNormalizer
from byou.intake.models import SpeakerCluster, SpeakerSegment


# ══════════════════════════════════════════════════════════
# DiarizationNormalizer
# ══════════════════════════════════════════════════════════

class TestNormalizer:
    def test_normalize_segment_ms_input(self):
        norm = DiarizationNormalizer()
        result = norm.normalize_segment({
            "start_ms": 1000, "end_ms": 5000, "text": "hello",
        })
        assert result["start_ms"] == 1000
        assert result["end_ms"] == 5000

    def test_normalize_segment_seconds_input(self):
        """If value < 1000, assume seconds and convert to ms."""
        norm = DiarizationNormalizer()
        result = norm.normalize_segment({
            "start": 2.5, "end": 8.0, "text": "hello",
        })
        assert result["start_ms"] == 2500
        assert result["end_ms"] == 8000

    def test_asr_artifact_cleanup(self):
        norm = DiarizationNormalizer()
        result = norm.normalize_segment({
            "start": 0, "end": 3, "text": "[unclear] hello ***",
        })
        assert "[unclear]" not in result["text"]
        assert "***" not in result["text"]
        assert "hello" in result["text"]

    def test_normalize_cluster(self):
        norm = DiarizationNormalizer()
        result = norm.normalize_cluster({
            "cluster_id": "SPK_01",
            "embedding": [0.1, 0.2],
            "segments": [
                {"start": 2, "end": 4, "text": "你好"},
                {"start": 5, "end": 7, "text": "再见"},
            ],
        })
        assert result["cluster_id"] == "SPK_01"
        assert len(result["segments"]) == 2
        assert result["segments"][0]["start_ms"] == 2000

    def test_normalize_cluster_dedup(self):
        norm = DiarizationNormalizer()
        result = norm.normalize_cluster({
            "cluster_id": "SPK_01",
            "segments": [
                {"start": 0, "end": 2, "text": "hello"},
                {"start": 0, "end": 2, "text": "hello"},  # duplicate
                {"start": 3, "end": 5, "text": "world"},
            ],
        })
        assert len(result["segments"]) == 2

    def test_speaker_label_as_cluster_id(self):
        norm = DiarizationNormalizer()
        result = norm.normalize_cluster({
            "speaker": "speaker_A",
            "segments": [],
        })
        assert result["cluster_id"] == "speaker_A"


# ══════════════════════════════════════════════════════════
# DiarizationAdapter
# ══════════════════════════════════════════════════════════

class TestAdapterFromSpeakers:
    def test_from_speakers_dict(self):
        adapter = DiarizationAdapter()
        raw = {
            "speakers": [
                {
                    "speaker": "SPK_01",
                    "segments": [
                        {"start": 0, "end": 2.5, "text": "你好，请问有什么产品"},
                    ],
                    "embedding": [0.1, 0.2, 0.3],
                },
                {
                    "speaker": "SPK_02",
                    "segments": [
                        {"start": 3.0, "end": 7.0, "text": "我们提供AI销售解决方案"},
                    ],
                },
            ]
        }
        clusters = adapter.process(raw)
        assert len(clusters) == 2
        assert clusters[0].cluster_id == "SPK_01"
        assert len(clusters[0].segments) == 1
        assert "产品" in clusters[0].segments[0].text
        assert clusters[1].cluster_id == "SPK_02"

    def test_pyannote_pipeline_format(self):
        """pyannote diarization + transcription combined."""
        adapter = DiarizationAdapter()
        raw = {
            "diarization": "PyAnnoteAnnotation(ref...)",
            "transcription": "whisper_transcription_output",
            "speakers": [
                {
                    "speaker": "SPEAKER_00",
                    "segments": [
                        {"start": 0.5, "end": 3.0, "text": "你好，我想了解一下"},
                    ],
                },
            ],
        }
        clusters = adapter.process(raw)
        assert len(clusters) == 1
        assert clusters[0].cluster_id == "SPEAKER_00"

    def test_single_speaker(self):
        adapter = DiarizationAdapter()
        clusters = adapter.process({
            "speakers": [
                {"speaker": "only", "segments": [{"start": 0, "end": 1, "text": "hi"}]},
            ],
        })
        assert len(clusters) == 1


class TestAdapterFlatSegments:
    def test_flat_segments_group_by_speaker(self):
        adapter = DiarizationAdapter()
        flat = [
            {"speaker": "SPK_A", "start": 0.0, "end": 2.0, "text": "hello"},
            {"speaker": "SPK_B", "start": 2.5, "end": 4.0, "text": "hi there"},
            {"speaker": "SPK_A", "start": 5.0, "end": 7.0, "text": "thanks"},
        ]
        clusters = adapter.process(flat)
        assert len(clusters) == 2
        assert clusters[0].cluster_id == "SPK_A"
        assert len(clusters[0].segments) == 2

    def test_flat_segments_no_speaker_key(self):
        adapter = DiarizationAdapter()
        flat = [
            {"speaker_id": "agent", "start": 0.0, "end": 2.0, "text": "hi"},
        ]
        clusters = adapter.process(flat)
        assert len(clusters) == 1
        assert clusters[0].cluster_id == "agent"

    def test_flat_segments_unknown_speaker(self):
        adapter = DiarizationAdapter()
        flat = [
            {"start": 0.0, "end": 1.0, "text": "?"},
        ]
        clusters = adapter.process(flat)
        assert len(clusters) == 1
        assert clusters[0].cluster_id == "SPK_UNKNOWN"

    def test_empty_input(self):
        adapter = DiarizationAdapter()
        clusters = adapter.process({})
        assert clusters == []

    def test_process_batch(self):
        adapter = DiarizationAdapter()
        clusters = adapter.process_batch([
            {"speakers": [{"speaker": "A", "segments": []}]},
            {"speakers": [{"speaker": "B", "segments": []}]},
        ])
        assert len(clusters) == 2


# ══════════════════════════════════════════════════════════
# Model integrity
# ══════════════════════════════════════════════════════════

class TestModelIntegrity:
    def test_speaker_cluster_is_intake_model(self):
        """SpeakerCluster must NOT be in channel_contract."""
        from byou.intake.models import SpeakerCluster as ImCluster
        assert ImCluster.__module__ == "byou.intake.models"

    def test_speaker_segment_fields(self):
        seg = SpeakerSegment(start_ms=100, end_ms=500, text="你好")
        d = seg.model_dump()
        assert "start_ms" in d
        assert "text" in d
        # No provider fields leaked
        assert "speaker" not in d  # provider label stripped
        assert "bbox" not in d
