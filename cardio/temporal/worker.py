"""Cardio Temporal Worker."""
from __future__ import annotations
import asyncio, logging, os, sys
from temporalio.client import Client
from temporalio.worker import Worker
from cardio.temporal.activities import (
    extraction_activity, research_activity, synthesis_activity,
    strategy_activity, critique_activity,
)
from cardio.temporal.workflows.analyze import CardioAnalyzeWorkflow

log = logging.getLogger("cardio.temporal.worker")


async def _run() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "127.0.0.1:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "cardio")
    task_queue = os.getenv("TEMPORAL_TASK_QUEUE", "cardio-task-queue")
    log.info("starting Cardio worker | tq=%s ns=%s addr=%s", task_queue, namespace, address)
    client = await Client.connect(address, namespace=namespace)
    worker = Worker(
        client, task_queue=task_queue,
        workflows=[CardioAnalyzeWorkflow],
        activities=[extraction_activity, research_activity, synthesis_activity, strategy_activity, critique_activity],
    )
    await worker.run()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    run()
