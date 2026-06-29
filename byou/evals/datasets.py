"""Dataset — 加载 / 校验 / 筛选 EvalCase.

支持 JSONL 文件（每行一个 EvalCase JSON），支持 tag/priority/severity 过滤。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Sequence

from .types import EvalCase, EvalSeverity

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class DatasetLoader:
    """从 JSONL 文件加载 EvalCase 集合。"""

    def __init__(self, fixtures_root: Path | None = None):
        self._root = fixtures_root or FIXTURES_DIR
        self._root.mkdir(parents=True, exist_ok=True)
        self._cases: dict[str, EvalCase] = {}

    # ── Load ───────────────────────────────────────────────

    def load(self, filenames: Sequence[str] | None = None) -> list[EvalCase]:
        """Load cases from one or more .jsonl files.

        If filenames is None, loads all .jsonl files under fixtures/.
        """
        if filenames is None:
            filenames = [p.name for p in self._root.glob("*.jsonl")]

        cases: list[EvalCase] = []
        for name in filenames:
            path = self._root / name
            if not path.exists():
                logger.warning("Dataset not found: %s", path)
                continue
            loaded = self._load_file(path)
            cases.extend(loaded)
            logger.info("Loaded %d cases from %s", len(loaded), name)

        # index
        self._cases = {c.case_id: c for c in cases}
        return cases

    def _load_file(self, path: Path) -> list[EvalCase]:
        cases: list[EvalCase] = []
        with open(path, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                try:
                    cases.append(EvalCase.model_validate_json(line))
                except Exception as exc:
                    logger.warning("Skipping invalid case at %s:%d — %s", path.name, line_no, exc)
        return cases

    # ── Filter ─────────────────────────────────────────────

    def filter(
        self,
        tags: list[str] | None = None,
        severity: EvalSeverity | None = None,
        min_priority: int | None = None,
        max_cases: int | None = None,
        skip_ci: bool = False,
    ) -> list[EvalCase]:
        """Filter loaded cases.

        Args:
            tags: require at least one matching tag.
            severity: require exact severity match.
            min_priority: require priority >= this.
            max_cases: truncate result.
            skip_ci: exclude skip_in_ci cases.
        """
        result: list[EvalCase] = []
        for c in self._cases.values():
            if skip_ci and c.skip_in_ci:
                continue
            if severity is not None and c.severity != severity:
                continue
            if min_priority is not None and c.priority < min_priority:
                continue
            if tags:
                if not any(t in c.tags for t in tags):
                    continue
            result.append(c)
            if max_cases is not None and len(result) >= max_cases:
                break

        # sort by priority desc, then severity
        sev_order = {EvalSeverity.CRITICAL: 0, EvalSeverity.HIGH: 1, EvalSeverity.MEDIUM: 2, EvalSeverity.LOW: 3}
        result.sort(key=lambda c: (c.priority * -1, sev_order.get(c.severity, 99), c.case_id))
        return result

    # ── Stats ───────────────────────────────────────────────

    @property
    def loaded_count(self) -> int:
        return len(self._cases)

    def get(self, case_id: str) -> EvalCase | None:
        return self._cases.get(case_id)

    # ── Write ──────────────────────────────────────────────

    def write_fixture(self, name: str, cases: list[EvalCase]) -> Path:
        path = self._root / name
        with open(path, "w", encoding="utf-8") as fh:
            for c in cases:
                fh.write(c.model_dump_json(exclude_none=True) + "\n")
        logger.info("Wrote %d cases to %s", len(cases), path)
        return path


# ── Convenience ────────────────────────────────────────────────

def load_golden_cases(loader: DatasetLoader | None = None) -> list[EvalCase]:
    """Load golden cases (pass cases)."""
    ld = loader or DatasetLoader()
    ld.load(["golden_cases.jsonl"])
    return list(ld._cases.values())


def load_bad_cases(loader: DatasetLoader | None = None) -> list[EvalCase]:
    """Load known-bad cases. """
    ld = loader or DatasetLoader()
    ld.load(["bad_cases.jsonl"])
    return list(ld._cases.values())


def load_edge_cases(loader: DatasetLoader | None = None) -> list[EvalCase]:
    """Load edge / boundary cases."""
    ld = loader or DatasetLoader()
    ld.load(["edge_cases.jsonl"])
    return list(ld._cases.values())
