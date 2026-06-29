"""Shared AsyncOpenAI client singleton.

Every Agent and tool reuses the **same** HTTP connection pool instead of
creating 5+ independent clients.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from byou.config import get_settings

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Return the shared AsyncOpenAI client, creating it on first call."""
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
        )
    return _client


def reset_client() -> None:
    """Force re-creation of the client (e.g. after config change)."""
    global _client
    _client = None

# ── Model tier support (v2) ───────────────────────────

from byou.core.model_router import ModelTier

_tier_clients: dict = {}

def get_client_for_tier(tier: ModelTier):
    """Return an AsyncOpenAI client for the given model tier."""
    from openai import AsyncOpenAI
    if tier in _tier_clients:
        return _tier_clients[tier]
    s = get_settings()
    client = AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url)
    _tier_clients[tier] = client
    return client


def get_model_for_tier(tier: ModelTier) -> str:
    """Return the model name for a given tier."""
    s = get_settings()
    return {
        ModelTier.CHEAP:  getattr(s, "model_cheap", "gpt-3.5-turbo"),
        ModelTier.MEDIUM: getattr(s, "model_medium", "gpt-4o-mini"),
        ModelTier.DEEP:   getattr(s, "model_deep", "gpt-4o"),
    }[tier]


def reset_client() -> None:
    """Force re-creation of the client (e.g. after config change)."""
    global _client
    _client = None
    _tier_clients.clear()

