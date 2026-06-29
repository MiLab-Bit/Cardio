"""Byou Execution Engine — 可靠执行与恢复子系统。

提供 checkpoint / pause-resume / retry-rerun-replay / crash-recovery / idempotency / signal-resume。

用法:
    from byou.production.execution import DurableCoordinator, MemoryStorage

    exec_engine = DurableCoordinator(storage=MemoryStorage())
    durable.create_run("run_001", "trace_001")
    durable.start_run("run_001")
    durable.start_stage("run_001", "extraction")
    durable.complete_stage("run_001", "extraction", input_snap={}, output_snap={})
    durable.complete_run("run_001")

    summary = durable.get_run_summary("run_001")
"""

from .coordinator import DurableCoordinator
from .storage import MemoryStorage, SQLiteStorage, BaseStorage
from .checkpoints import CheckpointManager
from .idempotency import IdempotencyGuard, is_protected_action
from .recovery import RecoveryCoordinator
from .replay import ReplayEngine
from .rerun import RerunEngine
from .signals import SignalManager, wait_for_external_signal
from .state_machine import RunStateMachine, StageStateMachine
from .reports import RecoveryReport, ReplayDiffReport, RerunReport, RunSummaryReport, build_run_summary

__all__ = [
    # Coordinator (main entry)
    "DurableCoordinator",
    # Storage
    "MemoryStorage",
    "SQLiteStorage",
    "BaseStorage",
    # Managers
    "CheckpointManager",
    "IdempotencyGuard",
    "RecoveryCoordinator",
    "ReplayEngine",
    "RerunEngine",
    "SignalManager",
    # State machines
    "RunStateMachine",
    "StageStateMachine",
    # Reports
    "RecoveryReport",
    "ReplayDiffReport",
    "RerunReport",
    "RunSummaryReport",
    "build_run_summary",
    # Helpers
    "is_protected_action",
    "wait_for_external_signal",
]
