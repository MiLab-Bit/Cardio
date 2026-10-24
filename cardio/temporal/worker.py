"""Cardio Temporal Worker（统一到 hermes_core.temporal.run_worker）。"""
from __future__ import annotations

from hermes_core.temporal import run_worker

from cardio.temporal.activities import (
    critique_activity,
    extraction_activity,
    research_activity,
    strategy_activity,
    synthesis_activity,
)
from cardio.temporal.workflows.analyze import CardioAnalyzeWorkflow


def run() -> None:
    run_worker(
        [CardioAnalyzeWorkflow],
        [
            extraction_activity,
            research_activity,
            synthesis_activity,
            strategy_activity,
            critique_activity,
        ],
        task_queue="cardio-task-queue",
        namespace="cardio",
        address="127.0.0.1:7233",
    )


if __name__ == "__main__":
    run()
