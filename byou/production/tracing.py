"""Byou Production — Tracing 层。

Trace / Span 关联:
- trace_id: 一次 pipeline 全局唯一
- run_id: 单次执行
- span_id: 单个操作 (stage/agent/tool)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from byou.production.types import RunIdentity


# ── Span 上下文 ──────────────────────────────────────────

class TraceSpan:
    """单次操作 trace span"""
    def __init__(
        self,
        name: str,
        trace_id: str = "",
        parent_span_id: str = "",
    ):
        self.name = name
        self.trace_id = trace_id
        self.span_id = f"span_{int(time.time() * 1e6) & 0xFFFFFF:06x}"
        self.parent_span_id = parent_span_id
        self.started_at = datetime.now(timezone.utc)
        self.completed_at: datetime | None = None
        self.attributes: dict[str, Any] = {}
        self.events: list[dict] = []

    def add_event(self, name: str, attributes: dict | None = None):
        self.events.append({
            "name": name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def finish(self):
        self.completed_at = datetime.now(timezone.utc)

    @property
    def duration_ms(self) -> float:
        if not self.completed_at:
            end = datetime.now(timezone.utc)
        else:
            end = self.completed_at
        return (end - self.started_at).total_seconds() * 1000

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": self.attributes,
            "events": self.events,
        }


class Tracer:
    """轻量 Trace 收集器。

    不引入 OpenTelemetry 依赖 — 输出 JSON trace 到日志即可。
    """

    def __init__(self):
        self._spans: list[TraceSpan] = []
        self._active: list[TraceSpan] = []

    def start_span(self, name: str, trace_id: str = "") -> TraceSpan:
        parent = self._active[-1] if self._active else None
        span = TraceSpan(
            name=name,
            trace_id=trace_id or (parent.trace_id if parent else ""),
            parent_span_id=parent.span_id if parent else "",
        )
        self._active.append(span)
        return span

    def end_span(self, span: TraceSpan):
        span.finish()
        if span in self._active:
            self._active.remove(span)
        self._spans.append(span)

    @contextmanager
    def span(self, name: str, trace_id: str = "", **attrs):
        s = self.start_span(name, trace_id)
        for k, v in attrs.items():
            s.set_attribute(k, v)
        try:
            yield s
        except Exception:
            s.add_event("exception", {"error": str(Exception)})
            raise
        finally:
            self.end_span(s)

    def flush(self) -> list[dict]:
        spans = [s.to_dict() for s in self._spans]
        self._spans.clear()
        return spans

    @property
    def active_count(self) -> int:
        return len(self._active)


# ── Pipeline 级 tracing ──────────────────────────────────

class PipelineTracer:
    """Pipeline 专用 Tracer。

    Usage:
        tracer = PipelineTracer("pipe_001", "trace_abc")
        with tracer.span("extraction"):
            ...
        tracer.finish()  # → 输出所有 span
    """

    def __init__(self, run_id: str, trace_id: str = ""):
        self.run_id = run_id
        self.trace_id = trace_id
        self._tracer = Tracer()
        self._started = time.time()
        self._spans: list[TraceSpan] = []

    def span(self, name: str, **attrs):
        return self._tracer.span(name, trace_id=self.trace_id, run_id=self.run_id, **attrs)

    def start_stage(self, name: str) -> TraceSpan:
        span = self._tracer.start_span(name, self.trace_id)
        span.set_attribute("run_id", self.run_id)
        span.set_attribute("type", "stage")
        self._spans.append(span)
        return span

    def end_stage(self, span: TraceSpan):
        self._tracer.end_span(span)

    def record_tool_call(self, tool_name: str, capability: str, duration_ms: float, status: str):
        span = self._tracer.start_span(f"tool:{tool_name}", self.trace_id)
        span.set_attribute("run_id", self.run_id)
        span.set_attribute("type", "tool")
        span.set_attribute("tool_name", tool_name)
        span.set_attribute("capability", capability)
        span.set_attribute("status", status)
        # 模拟延迟
        span.completed_at = datetime.now(timezone.utc)
        self._tracer.end_span(span)

    def finish(self) -> list[dict]:
        return self._tracer.flush()


# ── 全局单例 ──────────────────────────────────────────────

_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
