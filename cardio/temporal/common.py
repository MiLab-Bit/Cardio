"""Serializable Cardio Temporal input.

Only stable provider identifiers may enter Temporal history. Decrypted BYOK
credentials are resolved *inside* the Activity worker and never returned.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnalyzeInput:
    raw_text: str = ""
    raw_type: str = "text"  # text | card_image | dialogue (text is extracted before dispatch)
    provider_id: str | None = None
    owner: str = ""
    contact_id: str | None = None
