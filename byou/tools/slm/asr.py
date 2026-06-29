"""ASR Tool — audio transcription via local Whisper or API."""

from __future__ import annotations

import logging
from pathlib import Path

from byou.core.llm_client import get_client

logger = logging.getLogger(__name__)


class ASRTool:
    """Transcribe audio files to text."""

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._whisper_ok = self._check_whisper()
        self._model = None

    @staticmethod
    def _check_whisper() -> bool:
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            logger.warning("openai-whisper unavailable, will use Whisper API")
            return False

    def _load_model(self):
        if self._model is None and self._whisper_ok:
            import whisper
            logger.info("Loading Whisper model: %s", self.model_size)
            self._model = whisper.load_model(self.model_size)
        return self._model

    async def transcribe(self, audio_path: str, language: str | None = None) -> str:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if self._whisper_ok:
            return await self._whisper_transcribe(path, language)
        return await self._api_transcribe(path, language)

    async def _whisper_transcribe(self, path: Path, language: str | None) -> str:
        model = self._load_model()
        if model is None:
            raise RuntimeError("Whisper model failed to load")

        kwargs: dict = {}
        if language:
            kwargs["language"] = language
        result = model.transcribe(str(path), **kwargs)
        text = result.get("text", "").strip()
        logger.info("Whisper local: %d chars, lang=%s", len(text), result.get("language", "unknown"))
        return text

    async def _api_transcribe(self, path: Path, language: str | None) -> str:
        client = get_client()
        with path.open("rb") as f:
            resp = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language=language,
            )
        text = resp.text.strip()
        logger.info("Whisper API: %d chars", len(text))
        return text
