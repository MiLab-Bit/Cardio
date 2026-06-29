# byou/intake/card/__init__.py
"""Card intake adapter — PaddleOCR → BusinessCard normalization.

Provider payload stays here.  Only BusinessCard exits to extraction layer.
"""

from byou.intake.card.adapter import CardAdapter
from byou.intake.card.normalizer import CardFieldNormalizer

__all__ = ["CardAdapter", "CardFieldNormalizer"]
