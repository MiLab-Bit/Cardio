"""DAG-based pipeline executor.

Executes pipeline stages in dependency order, with parallel
execution for stages that have no unresolved dependencies.

Usage:
    executor = PipelineDAGExecutor(stages, max_concurrent=3)
    await executor.execute(context, orchestrator, card_path, audio_path, on_progress)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from byou.core.stage import Stage

logger = logging.getLogger(__name__)


class PipelineDAGExecutor:
    """Execute pipeline stages in DAG order with parallelism.

    Features:
    - Topological execution (respects deps)
    - Parallel execution within same batch
    - Cycle detection
    - Per-stage timeout + retry
    - Graceful error handling (on_stage_failure: "continue" or "fail_fast")
    """

    def __init__(
        self,
        stages: list[Stage],
        max_concurrent: int = 3,
        on_stage_failure: str = "continue",
    ):
        self.stages = stages
        self.max_concurrent = max_concurrent
        self.on_stage_failure = on_stage_failure
        self._validate()

    # ── Validation ───────────────────────────────────────────

    def _validate(self) -> None:
        """Validate stage configs: check deps exist, detect cycles."""
        stage_ids = {s.key for s in self.stages}

        # Check all deps reference valid stage ids
        for stage in self.stages:
            for dep in stage.deps:
                if dep not in stage_ids:
                    raise ValueError(
                        f"Stage '{stage.key}' depends on unknown stage '{dep}'. "
                        f"Available: {sorted(stage_ids)}"
                    )

        # Cycle detection via DFS
        self._check_cycle(stage_ids)

    def _check_cycle(self, stage_ids: set[str]) -> None:
        """DFS cycle detection on the dependency graph."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {sid: WHITE for sid in stage_ids}
        # Build reverse adjacency: stage → list of stages that depend on it
        # deps: A depends on B → edge B → A
        adj = {sid: [] for sid in stage_ids}
        for s in self.stages:
            for dep in s.deps:
                adj[dep].append(s.key)

        def dfs(node: str) -> None:
            color[node] = GRAY
            for nb in adj.get(node, []):
                if color[nb] == GRAY:
                    raise ValueError(f"Cycle detected in pipeline DAG involving stage '{nb}'")
                if color[nb] == WHITE:
                    dfs(nb)
            color[node] = BLACK

        for sid in stage_ids:
            if color[sid] == WHITE:
                dfs(sid)

    # ── Topological batching ─────────────────────────────────

    def _topological_batches(self) -> list[list[str]]:
        """Compute execution batches.

        Stages in the same batch have all dependencies resolved and can
        run in parallel.  Returns list of batches (each batch = list of
        stage keys).
        """
        stage_map = {s.key: s for s in self.stages}
        in_degree = {s.key: len(s.deps) for s in self.stages}

        # Reverse adjacency: dep → [stages that depend on dep]
        dependents: dict[str, list[str]] = {s.key: [] for s in self.stages}
        for s in self.stages:
            for dep in s.deps:
                dependents[dep].append(s.key)

        batches: list[list[str]] = []
        completed: set[str] = set()

        while len(completed) < len(stage_map):
            # Find all stages with in_degree == 0 and not yet completed
            ready = [sid for sid, deg in in_degree.items() if deg == 0 and sid not in completed]
            if not ready:
                # This shouldn't happen if validation passed
                raise RuntimeError("DAG executor stuck: no ready stage but not all completed")

            batches.append(ready)
            completed.update(ready)

            # Decrease in_degree for all dependents of completed stages
            for sid in ready:
                for dep_sid in dependents.get(sid, []):
                    in_degree[dep_sid] -= 1

        return batches

    # ── Stage execution helpers ──────────────────────────────

    async def _execute_stage(
        self,
        stage: Stage,
        ctx: Any,  # PipelineContext
        card_path: Optional[str],
        audio_path: Optional[str],
        on_progress: Optional[Callable],
        orchestrator: Any,  # Orchestrator
    ) -> tuple[bool, Any]:
        """Execute a single stage. Returns (success, result_or_error).

        Handles:
        - Agent lookup (skip if optional + not registered)
        - Timeout
        - Retry with backoff
        - Progress callbacks
        """
        await self._emit(on_progress, stage.label_start, {})

        agent = orchestrator.get_agent(stage.agent_key)
        if agent is None:
            if stage.required:
                return False, RuntimeError(
                    f"Required agent '{stage.agent_key}' (stage '{stage.key}') is not registered."
                )
            logger.debug("Optional agent '%s' not registered — skipping '%s'", stage.agent_key, stage.key)
            await self._emit(on_progress, stage.label_done, {"skipped": True})
            return True, None

        input_data = stage.input_builder(ctx, card_path, audio_path)

        last_err = None
        for attempt in range(1, stage.retry + 2):  # retry + 1 initial attempt
            try:
                if stage.timeout > 0:
                    result = await asyncio.wait_for(
                        agent.execute(input_data),
                        timeout=stage.timeout,
                    )
                else:
                    result = await agent.execute(input_data)

                # Success
                stage.output_handler(ctx, result)
                await self._emit(on_progress, stage.label_done, result)
                return True, result

            except asyncio.TimeoutError:
                last_err = f"Stage '{stage.key}' timed out after {stage.timeout}s (attempt {attempt})"
                logger.warning(last_err)
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "Stage '%s' failed (attempt %d/%d): %s",
                    stage.key, attempt, stage.retry + 1, exc,
                )

            if attempt <= stage.retry:
                backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s...
                logger.info("Retrying stage '%s' in %ds...", stage.key, backoff)
                await asyncio.sleep(backoff)

        # All retries exhausted
        err_msg = f"Stage '{stage.key}' failed after {stage.retry + 1} attempts: {last_err}"
        ctx.errors.append(err_msg)
        await self._emit(on_progress, "stage_error", {"stage": stage.key, "error": str(last_err)})
        return False, last_err

    async def _emit(self, cb: Optional[Callable], stage: str, data: dict) -> None:
        if cb:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(stage, data)
                else:
                    cb(stage, data)
            except Exception:
                logger.warning("Progress callback error for stage: %s", stage)

    # ── Main execution entry point ───────────────────────────

    async def execute(
        self,
        ctx: Any,  # PipelineContext
        orchestrator: Any,  # Orchestrator
        card_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        on_progress: Optional[Callable] = None,
        skip_stages: Optional[set[str]] = None,
    ) -> None:
        """Execute all stages in DAG order with parallelism.

        Args:
            ctx: PipelineContext (mutated in-place)
            orchestrator: Orchestrator instance (for agent registry)
            card_path: card image path (passed to input_builder)
            audio_path: audio path (passed to input_builder)
            on_progress: callback(stage_name, data)
            skip_stages: set of stage keys to skip
        """
        skip = skip_stages or set()
        batches = self._topological_batches()

        logger.info(
            "DAG executor: %d stages, %d batches, max_concurrent=%d",
            len(self.stages), len(batches), self.max_concurrent,
        )
        for batch_idx, batch in enumerate(batches):
            # Filter out skipped stages
            batch = [sid for sid in batch if sid not in skip and self._stage_key_to_agent_key(sid) not in skip]
            if not batch:
                continue

            logger.info(
                "Batch %d/%d: executing %s",
                batch_idx + 1, len(batches), batch,
            )

            # Execute batch in parallel with concurrency limit
            semaphore = asyncio.Semaphore(self.max_concurrent)

            async def _run_stage(sid: str):
                async with semaphore:
                    stage = self._get_stage(sid)
                    if stage is None:
                        return sid, False, None
                    return sid, *await self._execute_stage(
                        stage, ctx, card_path, audio_path, on_progress, orchestrator,
                    )

            results = await asyncio.gather(
                *(_run_stage(sid) for sid in batch),
                return_exceptions=False,
            )

            # Check for failures
            for item in results:
                sid = item[0]
                success = item[1]
                if not success:
                    if self.on_stage_failure == "fail_fast":
                        raise RuntimeError(f"Stage '{sid}' failed (on_stage_failure=fail_fast)")
                    # "continue": log and move on

        logger.info("DAG executor finished")

    # ── Helpers ──────────────────────────────────────────────

    def _get_stage(self, key: str) -> Optional[Stage]:
        for s in self.stages:
            if s.key == key:
                return s
        return None

    def _stage_key_to_agent_key(self, stage_key: str) -> str:
        """Convert a stage key to its agent key (for skip_stages backwards compat)."""
        for s in self.stages:
            if s.key == stage_key:
                return s.agent_key
        return stage_key
