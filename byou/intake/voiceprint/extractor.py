# byou/intake/voiceprint/extractor.py
"""Voiceprint extractor — extract speaker embedding from audio.

Uses SpeechBrain's pre-trained speaker recognition models.
Outputs a fixed-length embedding vector (192-dim for ECAPA-TDNN).

Usage:
    extractor = VoiceprintExtractor()
    embedding = await extractor.extract("path/to/audio.wav")
    # Returns: list[float] of length 192
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default model: SpeechBrain ECAPA-TDNN (192-dim embedding)
DEFAULT_MODEL = "speechbrain/spkrec-ecapa-voxceleb"
DEFAULT_SAMPLE_RATE = 16000


class VoiceprintExtractor:
    """Extract voiceprint embedding from audio file.

    Uses SpeechBrain's pre-trained speaker recognition model.
    Downloads model on first use (cached to ~/.speechbrain/).

    Attributes:
        model_loaded: Whether the model is loaded.
        embedding_dim: Dimension of output embedding (192 for ECAPA-TDNN).
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
    ):
        """
        Args:
            model_name: SpeechBrain model hub ID.
            device: "cpu" or "cuda" (requires GPU).
        """
        self.model_name = model_name
        self.device = device
        self._classifier = None
        self._loaded = False
        self.embedding_dim = 192  # ECAPA-TDNN default

    async def extract(self, audio_path: str | Path) -> list[float]:
        """Extract voiceprint embedding from audio file.

        Args:
            audio_path: Path to audio file (WAV/MP3/FLAC).

        Returns:
            list[float]: Embedding vector (192-dim).

        Raises:
            FileNotFoundError: Audio file not found.
            RuntimeError: Extraction failed.
        """
        # Check SpeechBrain availability FIRST
        if not self._loaded:
            await self._load_model()

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Extract embedding
        try:
            embedding = await self._extract_impl(audio_path)
            logger.info(
                "Extracted voiceprint: %s (dim=%d)",
                audio_path.name,
                len(embedding),
            )
            return embedding
        except Exception as e:
            logger.error("Voiceprint extraction failed: %s", e)
            raise RuntimeError(f"Voiceprint extraction failed: {e}") from e

    async def extract_batch(self, audio_paths: list[str | Path]) -> list[list[float]]:
        """Extract voiceprints from multiple audio files.

        Args:
            audio_paths: List of audio file paths.

        Returns:
            list[list[float]]: List of embedding vectors.
        """
        results = []
        for path in audio_paths:
            try:
                emb = await self.extract(path)
                results.append(emb)
            except Exception as e:
                logger.warning("Skipping %s: %s", path, e)
                results.append([])  # Empty embedding for failed
        return results

    async def _load_model(self) -> None:
        """Load SpeechBrain model (lazy loading)."""
        try:
            from speechbrain.pretrained import SpeakerRecognition

            logger.info("Loading SpeechBrain model: %s", self.model_name)
            self._classifier = SpeakerRecognition.from_hparams(
                source=self.model_name,
                run_opts={"device": self.device},
            )
            self._loaded = True
            logger.info("SpeechBrain model loaded successfully")
        except ImportError as e:
            logger.error(
                "SpeechBrain not installed. Install: pip install speechbrain torchaudio"
            )
            raise RuntimeError(
                "SpeechBrain not installed. "
                "Install with: pip install speechbrain torchaudio"
            ) from e
        except Exception as e:
            logger.error("Failed to load SpeechBrain model: %s", e)
            raise RuntimeError(f"Failed to load model: {e}") from e

    async def _extract_impl(self, audio_path: Path) -> list[float]:
        """Actual extraction implementation.

        Returns:
            list[float]: Normalized embedding vector.
        """
        import torch

        # Load audio and extract embedding
        # SpeechBrain's SpeakerRecognition.encode_batch() returns (batch, embedding)
        waveform = self._classifier.load_audio(str(audio_path))
        embedding = self._classifier.encode_batch(waveform)

        # Convert to list[float]
        emb_tensor = embedding.squeeze(0)  # Remove batch dim
        emb_list = emb_tensor.detach().cpu().numpy().tolist()

        # Ensure correct dimension
        if isinstance(emb_list[0], list):
            emb_list = emb_list[0]  # Nested list → flat

        # L2 normalization (standard for cosine similarity)
        import numpy as np
        emb_np = np.array(emb_list, dtype=np.float32)
        norm = np.linalg.norm(emb_np)
        if norm > 0:
            emb_np = emb_np / norm

        return emb_np.tolist()

    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._loaded

    def unload(self) -> None:
        """Unload model to free memory."""
        self._classifier = None
        self._loaded = False
        logger.info("VoiceprintExtractor unloaded")


# ── Helper: Mock extractor for testing ───────────────────────────────────

class MockVoiceprintExtractor:
    """Mock extractor for testing (no model download required).

    Generates random embeddings of specified dimension.
    """

    def __init__(self, embedding_dim: int = 192, seed: int = 42):
        self.embedding_dim = embedding_dim
        self._rng = __import__("random").Random(seed)
        self._loaded = True

    async def extract(self, audio_path: str | Path) -> list[float]:
        """Generate random embedding (mock).
        
        Uses hash of filename for determinism.
        """
        # Use hash of filename for deterministic output
        import hashlib
        path_str = str(audio_path)
        hash_obj = hashlib.md5(path_str.encode())
        seed = int(hash_obj.hexdigest()[:8], 16)
        
        rng = __import__("random").Random(seed)
        emb = [rng.gauss(0, 1) for _ in range(self.embedding_dim)]
        # L2 normalize
        norm = sum(x * x for x in emb) ** 0.5
        return [x / norm for x in emb]

    async def extract_batch(self, audio_paths: list[str | Path]) -> list[list[float]]:
        """Generate random embeddings for batch."""
        return [await self.extract(p) for p in audio_paths]

    def is_loaded(self) -> bool:
        return True

    def unload(self) -> None:
        pass
