"""Adaptive Harness Runtime — multi-agent orchestration with learning loop.

Three-plane architecture:
- Thinking Plane: multi-agent pipeline  (Stage-driven, declarative, DAG-executed)
- Execution Plane: CUA Runtime task execution
- Learning Loop: continuous feedback → strategy optimisation

Adding / removing / reordering pipeline stages:
  → Edit the YAML config in `byou/pipelines/*.yaml`
  → Or override `_stages` in a subclass.
  → No core code changes needed for stage order or deps.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, TypeVar

from byou.core.message_bus import MessageBus
from byou.core.runtime import CuaRuntime
from byou.core.learning_loop import LearningLoop
from byou.core.dag_executor import PipelineDAGExecutor
from byou.core.stage import Stage, C
from byou.agents.base import Agent
from byou.config import get_settings
from byou.models.customer import CustomerProfile, PipelineContext
from byou.models import BDStrategy

logger = logging.getLogger(__name__)


# ── Stage builders (input + output handlers) ────────────────

def _build_extraction(ctx: C, card: str | None, audio: str | None) -> dict[str, Any]:
    return {"card_image_path": card, "audio_file_path": audio}


def _handle_extraction(ctx: C, result: dict[str, Any]) -> None:
    ctx.raw_extraction = result
    ctx.agent_reports["extraction"] = {
        "agent_name": "extractor",
        "summary": result.get("summary", "客户信息提取完成"),
        "details": result,
        "confidence": result.get("confidence", 0.0),
        "generated_at": datetime.now().isoformat(),
    }
    profile_data = result.get("profile", {})
    if profile_data:
        try:
            ctx.profile = CustomerProfile(**profile_data)
        except Exception as exc:
            logger.warning("CustomerProfile validation: %s", exc)
            ctx.errors.append(f"Profile validation: {exc}")
            ctx.profile = CustomerProfile(name=profile_data.get("name", ""))
    if "raw_text" in result:
        ctx.raw_text = result["raw_text"]


def _build_research(ctx: C, card: str | None, audio: str | None) -> dict[str, Any]:
    return {
        "profile": ctx.profile.model_dump() if ctx.profile else {},
        "company_name": ctx.profile.company if ctx.profile else "",
        "person_name": ctx.profile.name if ctx.profile else "",
    }


def _handle_research(ctx: C, result: dict[str, Any]) -> None:
    ctx.research_result = result
    ctx.agent_reports["research"] = {
        "agent_name": "researcher",
        "summary": result.get("summary", "客户背景调研完成"),
        "details": result,
        "confidence": result.get("confidence", 0.0),
        "generated_at": datetime.now().isoformat(),
    }


def _build_synthesis(ctx: C, card: str | None, audio: str | None) -> dict[str, Any]:
    return {
        "profile": ctx.profile.model_dump() if ctx.profile else {},
        "research": ctx.research_result,
        "raw_text": ctx.raw_text,
    }


def _handle_synthesis(ctx: C, result: dict[str, Any]) -> None:
    ctx.synthesis_result = result
    ctx.agent_reports["synthesis"] = {
        "agent_name": "synthesizer",
        "summary": result.get("summary", "客户画像建模完成"),
        "details": result,
        "confidence": result.get("confidence", 0.0),
        "generated_at": datetime.now().isoformat(),
    }
    if "enriched_profile" in result:
        try:
            ctx.profile = CustomerProfile(**result["enriched_profile"])
        except Exception as exc:
            ctx.errors.append(f"Enriched profile validation: {exc}")
    ctx.intent_score = result.get("intent_score")
    ctx.customer_level = result.get("customer_level")


def _build_strategy(ctx: C, card: str | None, audio: str | None) -> dict[str, Any]:
    return {
        "profile": ctx.profile.model_dump() if ctx.profile else {},
        "synthesis": ctx.synthesis_result,
        "customer_level": ctx.customer_level,
        "intent_score": ctx.intent_score,
    }


def _handle_strategy(ctx: C, result: dict[str, Any]) -> None:
    ctx.strategy_result = result
    ctx.agent_reports["strategy"] = {
        "agent_name": "strategist",
        "summary": result.get("summary", "BD策略生成完成"),
        "details": result,
        "confidence": result.get("confidence", 0.0),
        "generated_at": datetime.now().isoformat(),
    }
    strategy_data = result.get("strategy", {})
    if strategy_data:
        try:
            ctx.bd_strategy = BDStrategy(**strategy_data)
        except Exception as exc:
            logger.warning("BDStrategy validation: %s", exc)
            ctx.errors.append(f"Strategy validation: {exc}")


def _build_critique(ctx: C, card: str | None, audio: str | None) -> dict[str, Any]:
    strategy_feed = getattr(ctx, 'bd_strategy', None)
    if strategy_feed is not None:
        strategy_feed = strategy_feed.model_dump()
    else:
        strategy_feed = getattr(ctx, 'strategy_result', {})
    return {
        "profile": ctx.profile.model_dump() if ctx.profile else {},
        "research": ctx.research_result,
        "synthesis": ctx.synthesis_result,
        "strategy": strategy_feed,
    }


def _handle_critique(ctx: C, result: dict[str, Any]) -> None:
    ctx.critique_result = result
    ctx.agent_reports["critique"] = {
        "agent_name": "critic",
        "summary": result.get("summary", "风险审核完成"),
        "details": result,
        "confidence": result.get("confidence", 0.0),
        "generated_at": datetime.now().isoformat(),
    }
    ctx.trust_score = result.get("trust_score")
    ctx.risk_alerts = result.get("risk_alerts", [])
    ctx.quality_passed = result.get("passed")


# ── Default pipeline definition ────────────────────────────────
# Dependency analysis for the default 5-stage pipeline:
#
#   extraction       → deps=[]              → batch 0
#   research        → deps=[extraction]     → batch 1
#   synthesis       → deps=[extraction, research] → batch 2
#   strategy        → deps=[synthesis]  → batch 3
#   critique        → deps=[synthesis]  → batch 3 (parallel with strategy!)
#
# With DAG executor: strategy + critique run in parallel (batch 3).
# Expected speedup: ~30 % for typical inputs.
# ─────────────────────────────────────────────────────────────────

DEFAULT_STAGES: list[Stage] = [
    Stage(
        key="extraction",
        agent_key="extractor",
        label_start="extracting",
        label_done="extraction_done",
        required=True,
        deps=[],
        input_builder=_build_extraction,
        output_handler=_handle_extraction,
    ),
    Stage(
        key="research",
        agent_key="researcher",
        label_start="researching",
        label_done="research_done",
        required=False,
        deps=["extraction"],
        input_builder=_build_research,
        output_handler=_handle_research,
    ),
    Stage(
        key="synthesis",
        agent_key="synthesizer",
        label_start="synthesizing",
        label_done="synthesis_done",
        required=False,
        deps=["extraction", "research"],
        input_builder=_build_synthesis,
        output_handler=_handle_synthesis,
    ),
    Stage(
        key="strategy",
        agent_key="strategist",
        label_start="strategizing",
        label_done="strategy_done",
        required=False,
        deps=["synthesis"],
        input_builder=_build_strategy,
        output_handler=_handle_strategy,
    ),
    Stage(
        key="critique",
        agent_key="critic",
        label_start="critiquing",
        label_done="critique_done",
        required=False,
        deps=["synthesis"],
        input_builder=_build_critique,
        output_handler=_handle_critique,
    ),
]

# Human-readable labels for generic progress events
STAGE_LABELS: dict[str, str] = {
    "pipeline_start":    "Pipeline started",
    "pipeline_complete": "Pipeline complete",
    "pipeline_error":    "Pipeline error",
}


# ── Orchestrator ──────────────────────────────────────────────────────

class Orchestrator:
    """Central orchestrator for the multi-agent pipeline.

    Stages are driven declaratively via YAML config or DEFAULT_STAGES.
    The DAG executor handles dependency ordering + parallel execution.

    To customise the pipeline:
    1. YAML config (preferred):
         set `pipeline_config_path = "byou/pipelines/my_pipeline.yaml"`
         in a subclass, or pass `config_path` to `__init__`.
    2. Subclass + override `_stages` (legacy, still supported).

    The DAG executor automatically:
    - Computes execution batches from `deps`
    - Runs stages in the same batch in parallel
    - Detects cycles in the dependency graph
    """

    # Override this in a subclass to customise the pipeline
    # without touching the source file.
    _stages: list[Stage] | None = None

    # Pipeline YAML config path. Override in subclass or set via env.
    pipeline_config_path: str | None = None

    def __init__(self, config_path: str | None = None) -> None:
        self._settings = get_settings()
        self.message_bus = MessageBus()
        self.cua_runtime = CuaRuntime(message_bus=self.message_bus)
        self.learning_loop = LearningLoop(message_bus=self.message_bus)

        self._agents: dict[str, Agent] = {}
        self._pipeline_sem = asyncio.Semaphore(self._settings.max_concurrent_pipelines)
        self._learn_lock = asyncio.Lock()

        # Load stages from config if provided
        config = config_path or self.__class__.pipeline_config_path
        if config:
            try:
                self._stages = self._load_stages_from_yaml(config)
                logger.info(
                    "Orchestrator ready (loaded %d stages from %s, max concurrent: %d)",
                    len(self._stages), config, self._settings.max_concurrent_pipelines,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to load pipeline config from %s: %s — using default stages",
                    config, exc,
                )
                self._stages = None  # fall back to DEFAULT_STAGES

        if self._stages is None:
            logger.info(
                "Orchestrator ready (default stages: %d, max concurrent: %d)",
                len(self.stages), self._settings.max_concurrent_pipelines,
            )

    # ── Properties ─────────────────────────────────────────────

    @property
    def stages(self) -> list[Stage]:
        """Return the stage list (YAML config > subclass hook > default)."""
        if self._stages is not None:
            return self._stages
        # Try loading from YAML config (if pipeline_config_path was set after init)
        if self.__class__.pipeline_config_path:
            try:
                self._stages = self._load_stages_from_yaml(self.__class__.pipeline_config_path)
                logger.info(
                    "Loaded %d stages from %s",
                    len(self._stages), self.__class__.pipeline_config_path,
                )
                return self._stages
            except Exception as exc:
                logger.warning(
                    "Failed to load pipeline config from %s: %s",
                    self.__class__.pipeline_config_path, exc,
                )
        return DEFAULT_STAGES

    # ── YAML config loader ─────────────────────────────────

    @staticmethod
    def _load_stages_from_yaml(path: str) -> list[Stage]:
        """Load pipeline stages from a YAML config file.

        YAML format:
            name: my_pipeline
            stages:
              - id: extraction
                agent_key: extractor
                deps: []
                ...
        """
        try:
            import yaml
        except ImportError:
            raise RuntimeError(
                "PyYAML not installed. Install with: pip install pyyaml"
            )

        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        stages = []
        for s_cfg in cfg.get("stages", []):
            sid = s_cfg["id"]
            stages.append(Stage(
                key=sid,
                agent_key=s_cfg["agent_key"],
                label_start=s_cfg.get("label_start", sid),
                label_done=s_cfg.get("label_done", sid + "_done"),
                required=s_cfg.get("required", True),
                deps=s_cfg.get("deps", []),
                timeout=s_cfg.get("timeout", 30),
                retry=s_cfg.get("retry", 2),
            ))
        return stages

    # ── Agent registry ───────────────────────────────────────

    def register_agent(self, name: str, agent: Agent) -> None:
        self._agents[name] = agent
        self.message_bus.register(name, agent)
        logger.info("Agent registered: %s (%s)", name, agent.__class__.__name__)

    def get_agent(self, name: str) -> Agent | None:
        return self._agents.get(name)

    # ── Pipeline ────────────────────────────────────────────────

    async def process_pipeline(
        self,
        *,
        card_image_path: str | None = None,
        audio_file_path: str | None = None,
        context: dict[str, Any] | None = None,
        on_progress: Callable[[str, dict], None] | None = None,
        skip_stages: set[str] | None = None,
    ) -> PipelineContext:
        """Execute the BD customer management pipeline.

        Args:
            card_image_path:  business card image path.
            audio_file_path:  meeting recording path.
            context:         extra context dict passed into PipelineContext.
            on_progress:     `(stage_name, data)` callback.
            skip_stages:     stage keys to skip, e.g.  `{"research", "synthesis"}`.
                             Both the full key ("research") and the agent key
                             ("researcher") are accepted for backwards compat.

        Returns:
            PipelineContext with all stage results populated.
        """
        skip = self._normalise_skip(skip_stages or set())
        pipeline_id = uuid.uuid4().hex[:12]

        ctx = PipelineContext(
            id=pipeline_id,
            started_at=datetime.now(),
            card_image_path=card_image_path,
            audio_file_path=audio_file_path,
            extra_context=context or {},
        )
        await self._emit(on_progress, "pipeline_start", {})

        async with self._pipeline_sem:
            try:
                await self._run_stages(ctx, card_image_path, audio_file_path, skip, on_progress)

                async with self._learn_lock:
                    self.learning_loop.record_execution(ctx)

                ctx.completed_at = datetime.now()
                await self._emit(on_progress, "pipeline_complete", {"pipeline": ctx})

            except Exception as exc:
                logger.exception("Pipeline error")
                ctx.errors.append(f"{type(exc).__name__}: {exc}")
                await self._emit(on_progress, "pipeline_error", {"error": str(exc)})

        return ctx

    # ── Stage execution (DAG-aware) ─────────────────────────────

    async def _run_stages(
        self,
        ctx: PipelineContext,
        card_path: str | None,
        audio_path: str | None,
        skip: set[str],
        on_progress: Callable[[str, dict], None] | None,
    ) -> None:
        """Execute stages via DAG executor (parallel when deps allow)."""
        executor = PipelineDAGExecutor(
            stages=self.stages,
            max_concurrent=self._settings.max_concurrent_pipelines,
        )
        await executor.execute(
            ctx=ctx,
            orchestrator=self,
            card_path=card_path,
            audio_path=audio_path,
            on_progress=on_progress,
            skip_stages=skip,
        )

    # ── Backwards-compatible skip normalisation ──────────────────

    @staticmethod
    def _normalise_skip(skip: set[str]) -> set[str]:
        """Accept both short keys ("researcher") and full keys ("research").

        Old code passed  {"researcher"}; new stage keys are  {"research"}.
        Normalise both so either works.
        """
        AGENT_KEY_TO_STAGE_KEY = {
            "extractor": "extraction",
            "researcher": "research",
            "synthesizer": "synthesis",
            "strategist": "strategy",
            "critic": "critique",
        }
        normalised = set(skip)
        for key in list(skip):
            if key in AGENT_KEY_TO_STAGE_KEY:
                normalised.add(AGENT_KEY_TO_STAGE_KEY[key])
            elif key in AGENT_KEY_TO_STAGE_KEY.values():
                normalised.add(key)   # already a stage key, keep as-is
        return normalised

    # ── Helpers ─────────────────────────────────────────────────

    async def _emit(self, cb: Callable | None, stage: str, data: dict) -> None:
        if cb:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(stage, data)
                else:
                    cb(stage, data)
            except Exception:
                logger.warning("Progress callback error: %s", stage)

    async def shutdown(self) -> None:
        async with self._learn_lock:
            self.learning_loop.persist()
        await self.cua_runtime.shutdown()
        logger.info("Orchestrator shut down")
