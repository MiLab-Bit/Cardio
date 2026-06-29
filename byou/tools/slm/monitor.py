"""SLM Performance Monitor — 详细的性能指标收集与分析。

功能:
1. 记录每次推理的延迟、置信度、升级率
2. 计算 P50/P95/P99 延迟
3. A/B 测试支持（对比不同模型）
4. 生成性能报告
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InferenceRecord:
    """单次推理记录"""
    timestamp: float
    model_id: str
    capability: str
    latency_ms: float
    confidence: float
    needs_escalation: bool
    input_length: int
    output_length: int
    cache_hit: bool = False


@dataclass
class ModelMetrics:
    """单个模型的性能指标"""
    model_id: str
    total_calls: int = 0
    cache_hits: int = 0
    escalations: int = 0
    latencies: list[float] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def p50_latency_ms(self) -> float:
        return statistics.median(self.latencies) if self.latencies else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def p99_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    @property
    def avg_confidence(self) -> float:
        return statistics.mean(self.confidences) if self.confidences else 0.0

    @property
    def escalation_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.escalations / self.total_calls

    @property
    def cache_hit_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.cache_hits / self.total_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "total_calls": self.total_calls,
            "cache_hits": self.cache_hits,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "escalations": self.escalations,
            "escalation_rate": round(self.escalation_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "avg_confidence": round(self.avg_confidence, 4),
        }


class SLMPerformanceMonitor:
    """SLM 性能监控器 — 统一的性能指标收集与分析"""

    def __init__(self, max_records: int = 10000):
        self.max_records = max_records
        self._records: list[InferenceRecord] = []
        self._metrics: dict[str, ModelMetrics] = defaultdict(lambda: ModelMetrics(model_id=""))

    def record_inference(self, record: InferenceRecord) -> None:
        """记录单次推理"""
        self._records.append(record)

        # 限制记录数量
        if len(self._records) > self.max_records:
            self._records = self._records[-self.max_records:]

        # 更新模型指标
        metrics = self._metrics[record.model_id]
        metrics.model_id = record.model_id
        metrics.total_calls += 1
        metrics.latencies.append(record.latency_ms)
        metrics.confidences.append(record.confidence)

        if record.needs_escalation:
            metrics.escalations += 1

        if record.cache_hit:
            metrics.cache_hits += 1

    def get_metrics(self, model_id: str) -> ModelMetrics | None:
        """获取指定模型的性能指标"""
        return self._metrics.get(model_id)

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """获取所有模型的性能指标"""
        return {k: v.to_dict() for k, v in self._metrics.items()}

    def compare_models(self, model_a: str, model_b: str) -> dict[str, Any]:
        """对比两个模型的性能"""
        metrics_a = self._metrics.get(model_a)
        metrics_b = self._metrics.get(model_b)

        if not metrics_a or not metrics_b:
            return {"error": "One or both models not found"}

        return {
            "model_a": metrics_a.to_dict(),
            "model_b": metrics_b.to_dict(),
            "comparison": {
                "latency_improvement": round(
                    (metrics_b.avg_latency_ms - metrics_a.avg_latency_ms) / max(metrics_b.avg_latency_ms, 1) * 100, 2
                ),
                "confidence_improvement": round(
                    (metrics_a.avg_confidence - metrics_b.avg_confidence) * 100, 2
                ),
                "escalation_reduction": round(
                    (metrics_b.escalation_rate - metrics_a.escalation_rate) * 100, 2
                ),
            },
        }

    def generate_report(self) -> str:
        """生成性能报告（文本格式）"""
        lines = ["SLM Performance Report", "=" * 50, ""]

        for model_id, metrics in sorted(self._metrics.items()):
            lines.append(f"Model: {model_id}")
            lines.append(f"  Total Calls: {metrics.total_calls}")
            lines.append(f"  Cache Hit Rate: {metrics.cache_hit_rate:.1%}")
            lines.append(f"  Escalation Rate: {metrics.escalation_rate:.1%}")
            lines.append(f"  Avg Latency: {metrics.avg_latency_ms:.1f} ms")
            lines.append(f"  P50 Latency: {metrics.p50_latency_ms:.1f} ms")
            lines.append(f"  P95 Latency: {metrics.p95_latency_ms:.1f} ms")
            lines.append(f"  Avg Confidence: {metrics.avg_confidence:.2f}")
            lines.append("")

        return "\n".join(lines)

    def export_json(self, filepath: str) -> None:
        """导出性能数据到 JSON"""
        data = {
            "generated_at": datetime.now().isoformat(),
            "models": self.get_all_metrics(),
            "recent_records": [
                {
                    "timestamp": r.timestamp,
                    "model_id": r.model_id,
                    "capability": r.capability,
                    "latency_ms": r.latency_ms,
                    "confidence": r.confidence,
                    "needs_escalation": r.needs_escalation,
                    "cache_hit": r.cache_hit,
                }
                for r in self._records[-100:]  # 最近 100 条
            ],
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Performance data exported to %s", filepath)

    def reset(self) -> None:
        """重置所有数据"""
        self._records.clear()
        self._metrics.clear()
        logger.info("Performance monitor reset")


# ── Global monitor instance ──────────────────────────────────

_default_monitor: SLMPerformanceMonitor | None = None


def get_monitor() -> SLMPerformanceMonitor:
    """获取全局性能监控器"""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = SLMPerformanceMonitor()
    return _default_monitor


def reset_monitor() -> None:
    """重置全局性能监控器"""
    global _default_monitor
    if _default_monitor:
        _default_monitor.reset()
    _default_monitor = SLMPerformanceMonitor()
