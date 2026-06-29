# tests/test_intake_voiceprint_integration.py
"""Integration tests: Voiceprint extraction → Intake pipeline."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from byou.intake.handler import IntakeHandler
from byou.intake.models import (
    IntakeProcessingResult,
    RawIntakePackage,
    VoiceprintProfile,
)


@pytest.fixture
def mock_gateways():
    """Create mock gateways for testing."""
    return {
        "identity_graph": None,
        "memory_gateway": MagicMock(),
        "crm_gateway": MagicMock(),
        "audit_gateway": MagicMock(),
        "review_gateway": MagicMock(),
        "conversation_gateway": MagicMock(),
    }


@pytest.fixture
def handler(mock_gateways):
    """Create IntakeHandler with mock gateways."""
    return IntakeHandler(**mock_gateways)


class TestVoiceprintExtractionIntegration:
    """Test voiceprint extraction integrated into Intake pipeline."""

    @pytest.mark.asyncio
    async def test_audio_paths_trigger_extraction(
        self, handler: IntakeHandler
    ):
        """Providing audio_paths → extracts voiceprints from audio."""
        audio_paths = ["tests/fixtures/audio1.wav", "tests/fixtures/audio2.wav"]
        raw = RawIntakePackage(audio_paths=audio_paths)

        mock_embeddings = [[0.1] * 192, [0.2] * 192]

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
        ) as mock_extract:
            mock_extract.return_value = mock_embeddings

            with patch.object(
                handler._assembler, "assemble", return_value={
                    "session": MagicMock(),
                    "memory_seeds": [],
                    "crm_seeds": [],
                    "audit_entries": [],
                    "review_required": False,
                }
            ):
                with patch.object(
                    handler._publisher, "publish", new_callable=AsyncMock
                ) as mock_publish:
                    mock_publish.return_value = IntakeProcessingResult(
                        session_id="test",
                        canonical_session={},
                    )
                    result = await handler.handle(raw)

        mock_extract.assert_called_once_with(audio_paths)
        assert isinstance(result, IntakeProcessingResult)

    @pytest.mark.asyncio
    async def test_no_audio_paths_skips_extraction(
        self, handler: IntakeHandler
    ):
        """No audio_paths → no extraction attempt."""
        raw = RawIntakePackage(audio_paths=[])

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
        ) as mock_extract:
            with patch.object(
                handler._assembler, "assemble", return_value={
                    "session": MagicMock(),
                    "memory_seeds": [],
                    "crm_seeds": [],
                    "audit_entries": [],
                    "review_required": False,
                }
            ):
                with patch.object(
                    handler._publisher, "publish", new_callable=AsyncMock
                ) as mock_publish:
                    mock_publish.return_value = IntakeProcessingResult(
                        session_id="test",
                        canonical_session={},
                    )
                    await handler.handle(raw)

        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_extraction_error_handled_gracefully(
        self, handler: IntakeHandler
    ):
        """Extraction error → warning logged, pipeline continues."""
        audio_paths = ["tests/fixtures/corrupt.wav"]
        raw = RawIntakePackage(audio_paths=audio_paths)

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Extraction failed"),
        ):
            with patch.object(
                handler._assembler, "assemble", return_value={
                    "session": MagicMock(),
                    "memory_seeds": [],
                    "crm_seeds": [],
                    "audit_entries": [],
                    "review_required": False,
                }
            ):
                with patch.object(
                    handler._publisher, "publish", new_callable=AsyncMock
                ) as mock_publish:
                    mock_publish.return_value = IntakeProcessingResult(
                        session_id="test",
                        canonical_session={},
                    )
                    result = await handler.handle(raw)

        assert isinstance(result, IntakeProcessingResult)

    @pytest.mark.asyncio
    async def test_audio_and_precomputed_voiceprints_merge(
        self, handler: IntakeHandler
    ):
        """Both audio_paths AND voiceprints provided → merged."""
        audio_paths = ["tests/fixtures/audio.wav"]
        precomputed_vp = VoiceprintProfile(
            uid="existing_uid",
            embedding=[0.5] * 192,
        )
        raw = RawIntakePackage(
            audio_paths=audio_paths,
            voiceprints=[precomputed_vp],
        )

        mock_embeddings = [[0.3] * 192]

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
        ) as mock_extract:
            mock_extract.return_value = mock_embeddings

            with patch.object(
                handler._extractor,
                "extract_voiceprints",
                wraps=handler._extractor.extract_voiceprints,
            ) as spy_adapt:
                with patch.object(
                    handler._assembler, "assemble", return_value={
                        "session": MagicMock(),
                        "memory_seeds": [],
                        "crm_seeds": [],
                        "audit_entries": [],
                        "review_required": False,
                    }
                ):
                    with patch.object(
                        handler._publisher, "publish", new_callable=AsyncMock
                    ) as mock_publish:
                        mock_publish.return_value = IntakeProcessingResult(
                            session_id="test",
                            canonical_session={},
                        )
                        await handler.handle(raw)

        mock_extract.assert_called_once_with(audio_paths)
        spy_adapt.assert_called_once()

    @pytest.mark.asyncio
    async def test_voiceprint_passed_to_matcher(
        self, handler: IntakeHandler
    ):
        """Extracted voiceprints → passed to IdentityMatcher."""
        audio_paths = ["tests/fixtures/audio.wav"]
        raw = RawIntakePackage(audio_paths=audio_paths)

        mock_embeddings = [[0.1] * 192]

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
        ) as mock_extract:
            mock_extract.return_value = mock_embeddings

            with patch.object(
                handler._extractor,
                "match_all",
                wraps=handler._extractor.match_all,
            ) as spy_match:
                with patch.object(
                    handler._assembler, "assemble", return_value={
                        "session": MagicMock(),
                        "memory_seeds": [],
                        "crm_seeds": [],
                        "audit_entries": [],
                        "review_required": False,
                    }
                ):
                    with patch.object(
                        handler._publisher, "publish", new_callable=AsyncMock
                    ) as mock_publish:
                        mock_publish.return_value = IntakeProcessingResult(
                            session_id="test",
                            canonical_session={},
                        )
                        await handler.handle(raw)

        spy_match.assert_called_once()
        call_args = spy_match.call_args
        voiceprints_arg = call_args[1]["voiceprints"]
        assert len(voiceprints_arg) >= 1


class TestEndToEndMocked:
    """End-to-end tests with fully mocked dependencies."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_audio(
        self, handler: IntakeHandler
    ):
        """Full pipeline: audio → extraction → matching → assembly → publish."""
        audio_paths = ["tests/fixtures/speaker.wav"]
        raw = RawIntakePackage(audio_paths=audio_paths)

        mock_embedding = [0.1] * 192

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
            return_value=[mock_embedding],
        ):
            with patch.object(
                handler._publisher, "publish", new_callable=AsyncMock
            ) as mock_publish:
                mock_publish.return_value = IntakeProcessingResult(
                    session_id="test",
                    canonical_session={},
                )
                result = await handler.handle(raw)

        assert isinstance(result, IntakeProcessingResult)
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_full_pipeline_card_plus_audio(
        self, handler: IntakeHandler
    ):
        """Card + audio → cross-modal matching."""
        from byou.intake.models import BusinessCard

        audio_paths = ["tests/fixtures/speaker.wav"]
        card = BusinessCard(name="张三", phone="13800138000")
        raw = RawIntakePackage(audio_paths=audio_paths, cards=[card])

        mock_embedding = [0.1] * 192

        with patch.object(
            handler._extractor._voiceprint_extractor,
            "extract_batch",
            new_callable=AsyncMock,
            return_value=[mock_embedding],
        ):
            with patch.object(
                handler._publisher, "publish", new_callable=AsyncMock
            ) as mock_publish:
                mock_publish.return_value = IntakeProcessingResult(
                    session_id="test",
                    canonical_session={},
                )
                result = await handler.handle(raw)

        assert isinstance(result, IntakeProcessingResult)
        assert len(result.errors) == 0
