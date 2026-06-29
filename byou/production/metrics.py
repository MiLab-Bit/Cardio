"""Byou Production — Metrics Collector.

内存态 metrics 收集器:
- Counter / Gauge / Histogram
- pipeline/stage/agent/tool 四级标签
- Prometheus 兼容 scrape endpoint
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from byou.production.types import MetricSample, MetricsSnapshot

# ═══════════════════════════════════════════════════════════════
# 指标基类
# ═══════════════════════════════════════════════════════════════

class _Metric:
    def __init__(self, name: str, help_text: str = "", unit: str = ""):
        self.name = name
        self.help = help_text
        self.unit = unit


class Counter(_Metric):
    """单调递增计数器"""
    def __init__(self, name: str, help_text: str = ""):
        super().__init__(name, help_text, "count")
        self._values: dict[tuple, int] = defaultdict(int)
        self._lock = Lock()

    def inc(self, labels: dict[str, str] | None = None, amount: int = 1):
        key = _labels_key(labels)
        with self._lock:
            self._values[key] += amount

    def get(self, labels: dict[str, str] | None = None) -> int:
        return self._values.get(_labels_key(labels), 0)

    def snapshot(self) -> list[MetricSample]:
        ts = datetime.now(timezone.utc)
        with self._lock:
            return [
                MetricSample(
                    name=self.name, value=v, timestamp=ts,
                    labels=dict(zip(["label"], [str(k)])) if k else {},
                    unit=self.unit,
                )
                for k, v in self._values.items()
            ]


class Gauge(_Metric):
    """可增可减的瞬时值"""
    def __init__(self, name: str, help_text: str = ""):
        super().__init__(name, help_text, "")
        self._value: float = 0.0
        self._lock = Lock()

    def set(self, value: float):
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0):
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0):
        with self._lock:
            self._value -= amount

    def get(self) -> float:
        with self._lock:
            return self._value

    def snapshot(self) -> list[MetricSample]:
        return [
            MetricSample(
                name=self.name, value=self._value,
                timestamp=datetime.now(timezone.utc), unit=self.unit,
            )
        ]


class Histogram(_Metric):
    """分桶统计（用于延迟等）"""
    def __init__(self, name: str, buckets: list[float] | None = None, help_text: str = ""):
        super().__init__(name, help_text, "ms")
        self.buckets = buckets or [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000]
        self._lock = Lock()
        self._count = 0
        self._sum = 0.0
        self._bucket_counts = defaultdict(int)

    def observe(self, value: float):
        with self._lock:
            self._count += 1
            self._sum += value
            for b in self.buckets:
                if value <= b:
                    self._bucket_counts[b] += 1
                    break
            else:
                self._bucket_counts[float("inf")] += 1

    def snapshot(self) -> list[MetricSample]:
        ts = datetime.now(timezone.utc)
        with self._lock:
            samples = [
                MetricSample(name=f"{self.name}_count", value=self._count, timestamp=ts, unit="count"),
                MetricSample(name=f"{self.name}_sum", value=self._sum, timestamp=ts, unit=self.unit),
            ]
            for b, c in self._bucket_counts.items():
                samples.append(
                    MetricSample(
                        name=f"{self.name}_bucket", value=c, timestamp=ts,
                        labels={"le": str(b)}, unit="count",
                    )
                )
        return samples

    @property
    def avg(self) -> float:
        with self._lock:
            return self._sum / self._count if self._count > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
# Metrics Collector
# ═══════════════════════════════════════════════════════════════

def _labels_key(labels: dict[str, str] | None) -> tuple:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


class MetricsCollector:
    """全局 metrics 收集器。

    预定义指标:
    - byou_pipelines_total: Counter (status)
    - byou_stage_duration_ms: Histogram (stage)
    - byou_agent_duration_ms: Histogram (agent)
    - byou_tool_calls_total: Counter (tool, status)
    - byou_tool_duration_ms: Histogram (tool)
    - byou_llm_tokens_total: Counter (type: prompt/completion)
    - byou_llm_duration_ms: Histogram
    - byou_browser_sessions: Gauge
    - byou_errors_total: Counter (category)
    - byou_active_pipelines: Gauge
    - byou_circuit_breaker_opens: Counter
    - byou_persistence_checkpoints: Counter (status)
    """

    def __init__(self):
        self.pipelines_total = Counter("byou_pipelines_total", "Total pipeline completions by status")
        self.stage_duration_ms = Histogram("byou_stage_duration_ms", help_text="Stage duration in ms")
        self.agent_duration_ms = Histogram("byou_agent_duration_ms", help_text="Agent execution duration")
        self.tool_calls_total = Counter("byou_tool_calls_total", "Total tool calls by tool and status")
        self.tool_duration_ms = Histogram("byou_tool_duration_ms", help_text="Tool call duration")
        self.llm_tokens_total = Counter("byou_llm_tokens_total", "LLM tokens by type")
        self.llm_duration_ms = Histogram("byou_llm_duration_ms", help_text="LLM call duration")
        self.browser_sessions = Gauge("byou_browser_sessions", "Active browser sessions")
        self.errors_total = Counter("byou_errors_total", "Total errors by category")
        self.active_pipelines = Gauge("byou_active_pipelines", "Currently active pipelines")
        self.circuit_breaker_opens = Counter("byou_circuit_breaker_opens", "Circuit breaker opens")
        self.persistence_checkpoints = Counter("byou_persistence_checkpoints", "Persistence checkpoints")

        self._start_time = time.time()
        self._custom: dict[str, _Metric] = {}
        self._lock = Lock()

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    def register(self, metric: _Metric):
        with self._lock:
            self._custom[metric.name] = metric

    def get(self, name: str) -> _Metric | None:
        return self._custom.get(name)

    def snapshot(self) -> MetricsSnapshot:
        samples: list[MetricSample] = []
        for metric in [
            self.pipelines_total, self.stage_duration_ms, self.agent_duration_ms,
            self.tool_calls_total, self.tool_duration_ms, self.llm_tokens_total,
            self.llm_duration_ms, self.browser_sessions, self.errors_total,
            self.active_pipelines, self.circuit_breaker_opens, self.persistence_checkpoints,
        ]:
            samples.extend(metric.snapshot())
        with self._lock:
            for m in self._custom.values():
                samples.extend(m.snapshot())
        return MetricsSnapshot(samples=samples)

    def prometheus_text(self) -> str:
        """Prometheus scrape 格式"""
        lines = []
        snap = self.snapshot()
        for s in snap.samples:
            name = s.name
            label_str = ""
            if s.labels:
                label_parts = [f'{k}="{v}"' for k, v in s.labels.items()]
                label_str = "{" + ",".join(label_parts) + "}"
            lines.append(f"# HELP {name} \n# TYPE {name} gauge\n{name}{label_str} {s.value}")
        return "\n".join(lines) + "\n"


# ── 全局单例 ──────────────────────────────────────────────

_collector: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
