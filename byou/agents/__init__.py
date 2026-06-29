"""Byou multi-agent system.

All agents are created from declarative configs in :mod:`byou.agents.configs`.
"""

from __future__ import annotations

from byou.agents.base import Agent
from byou.agents.configs import AGENT_CONFIGS


def create_agent(name: str) -> Agent:
    """Create an agent from its declarative config."""
    cfg = AGENT_CONFIGS.get(name)
    if cfg is None:
        raise KeyError(f"Unknown agent: {name}. Available: {list(AGENT_CONFIGS)}")
    return Agent(name, cfg)


def create_all_agents() -> dict[str, Agent]:
    """Create all configured agents at once."""
    return {name: create_agent(name) for name in AGENT_CONFIGS}


# Backward-compatible aliases for direct imports
def ExtractorAgent(**kw):
    return create_agent("extractor")

def ResearcherAgent(**kw):
    return create_agent("researcher")

def SynthesizerAgent(**kw):
    return create_agent("synthesizer")

def StrategistAgent(**kw):
    return create_agent("strategist")

def CriticAgent(**kw):
    return create_agent("critic")


__all__ = [
    "Agent", "AGENT_CONFIGS",
    "create_agent", "create_all_agents",
    "ExtractorAgent", "ResearcherAgent", "SynthesizerAgent",
    "StrategistAgent", "CriticAgent",
]
