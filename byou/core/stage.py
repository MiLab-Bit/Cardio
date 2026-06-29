"""Pipeline Stage declaritive config."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar#

# Re-export for backward compat
from byou.models.customer import PipelineContext

C = TypeVar("C", bound=PipelineContext)


@dataclass
class Stage:
    key: str
    agent_key: str
    label_start: str
    label_done: str
    required: bool = True
    deps: list[str] = field(default_factory=list)
    timeout: int = 30
    retry: int = 2
    # Build the input dict for this stage; default works for most agents.
    input_builder: Callable[[C, str | None, str | None], dict[str, Any]] = field(
        default=lambda ctx, card, audio: {
            "card_image_path": card,
            "audio_file_path": audio,
        }
    )
    # Handle the agent result; write it back into PipelineContext.
    output_handler: Callable[[C, dict[str, Any]], None] = field(default=lambda ctx, result: None)

    @classmethod
    def simple(
        cls,
        key: str,
        agent_key: str,
        label_start: str,
        label_done: str,
        required: bool = True,
        deps: list[str] | None = None,
        timeout: int = 30,
        retry: int = 2,
        input_builder: Callable[[C, str | None, str | None], dict[str, Any]] | None = None,
        output_handler: Callable[[C, dict[str, Any]], None] | None = None,
    ) -> "Stage":
        """Convenience factory for the 80 % case."""
        ib = input_builder or (lambda ctx, card, audio: {
            "card_image_path": card,
            "audio_file_path": audio,
        })
        oh = output_handler or (lambda ctx, result: None)
        return cls(key, agent_key, label_start, label_done, required,
                    deps or [], timeout, retry, ib, oh)
