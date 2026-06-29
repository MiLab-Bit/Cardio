"""Byou — Business You: AI-powered BD multi-agent system.

Architecture (three-plane):
  Thinking Plane:   multi-agent pipeline           (Extractor→Researcher→Synthesizer→Strategist→Critic)
  Execution Plane:  CUA runtime                    (Perception→SemanticAlign→StateModeling→Planning→Execution→Validation)
  Learning Loop:    continual weight optimisation  (record_execution → adjust_weights → persist)

Quick start:
  >>> from byou.config import settings
  >>> from byou.core.orchestrator import Orchestrator
  >>> orch = Orchestrator()
  >>> orch.register_agent("extractor", ExtractorAgent())
  >>> # ... register all agents
  >>> ctx = await orch.process_pipeline(card_image_path="path/to/card.jpg")
"""

__version__ = "0.1.0"
