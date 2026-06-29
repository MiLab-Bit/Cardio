# Learning Loop 学习循环

## 文件

`byou/core/learning_loop.py` → `LearningLoop`

## 职责

不训练模型，而是通过**采集执行指标**和**调节 Agent 权重**优化 Pipeline 表现。

## 架构

```
┌────────────────────────────────────────────────┐
│               Learning Loop                     │
│                                                 │
│  Pipeline 执行 → 记录指标 → 滑动窗口            │
│                   ↓                             │
│              调整 Agent 权重                    │
│                   ↓                             │
│              持久化到磁盘                        │
│                   ↓                             │
│              生成洞察报告                        │
└────────────────────────────────────────────────┘
```

## ExecutionTrace

```python
class ExecutionTrace:
    trace_id: str             # 追踪 ID
    timestamp: datetime
    pipeline_id: str          # 关联的 Pipeline ID
    customer_name: str
    company: str
    metrics: {
        "trust_score": float,        # Critic 评分
        "intent_score": float,       # Synthesizer 评分
        "quality_passed": float,     # 质检结果 (1.0/0.0)
        "error_count": int,          # 错误数
        "pipeline_duration_ms": int, # 执行耗时
    }
    agent_performance: {
        "extractor": {"confidence": float, "errors": int},
        "researcher": {"confidence": float, "errors": int},
        "synthesizer": {"customer_level": str, "errors": int},
        "strategist": {"risk_count": int, "errors": int},
        "critic": {"trust_score": float, "errors": int},
    }
```

## 权重调节机制

```python
class LearningLoop:
    strategy_weights: dict = {
        "extractor": 1.0,
        "researcher": 1.0,
        "synthesizer": 1.0,
        "strategist": 1.0,
        "critic": 1.0,
    }
```

### 调节规则

| 触发条件 | 权重变化 | 变化量 |
|---------|---------|--------|
| `quality_passed == False` | Critic +0.1, 出错环节 -0.05 | ±0.05-0.1 |
| `intent_score < 0.3` | Synthesizer -0.05, Researcher +0.05 | ±0.05 |
| 某 Agent 连续 3 次 `errors > 0` | 该 Agent -0.1 | -0.1 |
| 连续 5 次 `quality_passed == True` | 所有 Agent +0.02 | +0.02 |

权重范围: `[0.5, 2.0]`，超出截断。

## 滑动窗口

只保留最近 **100 条** 执行记录，避免内存增长和过时数据影响。

## 持久化

```python
def persist() -> None:        # 保存到 data/learning_state.json
def _load() -> None:          # 从磁盘恢复
```

存储内容:
- `strategy_weights`
- `performance_history` (最近 100 条)
- `last_updated`

## get_insights() 输出

```python
# 有数据时
{
    "status": "ok",
    "total_executions": 42,
    "recent_avg_trust_score": 0.82,
    "recent_avg_intent_score": 0.65,
    "recent_quality_pass_rate": 0.85,
    "trend": "improving",
    "strategy_weights": {...},
}

# 无数据时
{"status": "no_data"}
```
