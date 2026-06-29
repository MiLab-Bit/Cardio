# tests/test_voiceprint_extractor.py
"""Tests for VoiceprintExtractor and MockVoiceprintExtractor."""

import pytest
from pathlib import Path

from byou.intake.voiceprint.extractor import (
    MockVoiceprintExtractor,
    VoiceprintExtractor,
)


class TestMockVoiceprintExtractor:
    """Test mock extractor (no model needed)."""

    @pytest.fixture
    def extractor(self) -> MockVoiceprintExtractor:
        return MockVoiceprintExtractor(embedding_dim=192, seed=42)

    @pytest.mark.asyncio
    async def test_extract_returns_list(self, extractor: MockVoiceprintExtractor):
        """Extract returns a list of floats."""
        emb = await extractor.extract("dummy.wav")
        assert isinstance(emb, list)
        assert len(emb) == 192
        assert all(isinstance(v, float) for v in emb)

    @pytest.mark.asyncio
    async def test_extract_normalized(self, extractor: MockVoiceprintExtractor):
        """Embedding should be L2-normalized (norm ≈ 1.0)."""
        emb = await extractor.extract("dummy.wav")
        import math

        norm = math.sqrt(sum(v * v for v in emb))
        assert abs(norm - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_extract_deterministic(self, extractor: MockVoiceprintExtractor):
        """Same file → same embedding (deterministic)."""
        emb1 = await extractor.extract("audio1.wav")
        emb2 = await extractor.extract("audio1.wav")
        assert emb1 == emb2

    @pytest.mark.asyncio
    async def test_extract_different_files(self, extractor: MockVoiceprintExtractor):
        """Different files → different embeddings."""
        emb1 = await extractor.extract("audio1.wav")
        emb2 = await extractor.extract("audio2.wav")
        assert emb1 != emb2

    @pytest.mark.asyncio
    async def test_extract_batch(self, extractor: MockVoiceprintExtractor):
        """Batch extraction returns list of embeddings."""
        paths = ["a.wav", "b.wav", "c.wav"]
        embs = await extractor.extract_batch(paths)
        assert len(embs) == 3
        assert all(len(e) == 192 for e in embs)

    @pytest.mark.asyncio
    async def test_extract_batch_handles_errors(
        self, extractor: MockVoiceprintExtractor
    ):
        """Batch continues on error (returns [] for failed)."""
        paths = ["valid.wav", "nonexistent.wav"]
        # Mock won't fail on missing file, but real extractor will
        embs = await extractor.extract_batch(paths)
        assert len(embs) == 2

    def test_is_loaded(self, extractor: MockVoiceprintExtractor):
        assert extractor.is_loaded() is True

    def test_unload(self, extractor: MockVoiceprintExtractor):
        extractor.unload()  # Should not raise
        assert extractor.is_loaded() is True  # Mock stays loaded

    def test_embedding_dim(self, extractor: MockVoiceprintExtractor):
        assert extractor.embedding_dim == 192


class TestVoiceprintExtractorInit:
    """Test real extractor initialization (without loading model)."""

    def test_init_default(self):
        ext = VoiceprintExtractor()
        assert ext.model_name == "speechbrain/spkrec-ecapa-voxceleb"
        assert ext.device == "cpu"
        assert ext.embedding_dim == 192
        assert ext.is_loaded() is False

    def test_init_custom(self):
        ext = VoiceprintExtractor(model_name="custom/model", device="cuda")
        assert ext.model_name == "custom/model"
        assert ext.device == "cuda"

    def test_unload(self):
        ext = VoiceprintExtractor()
        ext.unload()
        assert ext.is_loaded() is False


class TestVoiceprintExtractorImportError:
    """Test that helpful error is raised when SpeechBrain not installed."""

    @pytest.mark.asyncio
    async def test_extract_without_speechbrain(self):
        """Should raise RuntimeError with install hint."""
        # This test assumes SpeechBrain is not installed
        # Skip if actually installed
        try:
            import speechbrain  # noqa: F401

            pytest.skip("SpeechBrain is installed, cannot test import error")
        except ImportError:
            pass

        ext = VoiceprintExtractor()
        with pytest.raises(RuntimeError, match="SpeechBrain not installed"):
            await ext.extract("dummy.wav")


class TestExtractorIntegration:
    """Integration tests (require SpeechBrain installed)."""

    @pytest.fixture(scope="module")
    def real_extractor(self):
        """Load real extractor (skip if SpeechBrain not available)."""
        try:
            ext = VoiceprintExtractor(device="cpu")
            return ext
        except RuntimeError:
            pytest.skip("SpeechBrain not installed")

    @pytest.mark.skipif(
        True,  # Skip by default (requires model download)
        reason="Requires SpeechBrain model download (~80MB)",
    )
    @pytest.mark.asyncio
    async def test_real_extract(self, real_extractor: VoiceprintExtractor):
        """Test with real audio file."""
        # Need a real audio file
        audio_path = Path("tests/fixtures/sample_audio.wav")
        if not audio_path.exists():
            pytest.skip("Test audio file not found")

        emb = await real_extractor.extract(audio_path)
        assert len(emb) == 192
        assert all(isinstance(v, float) for v in emb)

        # Check normalized
        import math

        norm = math.sqrt(sum(v * v for v in emb))
        assert abs(norm - 1.0) < 1e-3
