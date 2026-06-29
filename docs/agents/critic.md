# Critic Agent — 质检审核

## 文件

`byou/agents/critic.py` → `CriticAgent`

## 职责

作为 Pipeline 最后一道关卡，审核全部上游输出，计算可信度评分，决定策略是否通过质检。

## 处理流程

```
全部上游输出 (Extractor + Researcher + Synthesizer + Strategist)
  ↓
LLM 多维度审核
  ↓
{
  trust_score: 0.0-1.0,
  quality_passed: bool,
  checks: [CheckResult],
  suggestions: [str],
}
```

## 输入

```python
{
    "pipeline_context": PipelineContext,  # 完整上下文
}
```

## 输出

```python
{
    "trust_score": float,        # 综合可信度 (0-1)
    "quality_passed": bool,      # 是否通过
    "checks": [
        {
            "name": str,         # 检查项名称
            "passed": bool,
            "detail": str,       # 检查详情
            "score": float,      # 单项得分
        }
    ],
    "suggestions": [str],        # 改进建议
    "risk_alerts": [str],        # 风险告警
    "recommended_rerun": bool,   # 是否建议重跑
}
```

## 审核维度

| 维度 | 权重 | 检查内容 |
|------|------|----------|
| 数据完整性 | 25% | 客户姓名、公司、联系方式是否齐全 |
| 信息一致性 | 20% | OCR 与搜索结果的姓名/公司是否一致 |
| 逻辑合理性 | 20% | 等级评定是否与画像匹配 |
| 策略可行性 | 20% | Talking Point 是否具体可执行 |
| 风险评估 | 15% | 是否遗漏明显风险 |

## 评分规则

```python
trust_score = Σ(维度得分 × 权重)
quality_passed = trust_score >= 0.6  # 阈值可配置
```

## 反馈闭环

1. **不通过**: 标记 `recommended_rerun = True`，列出具体修改点
2. **低分但通过**: 标记 `suggestions`，允许输出但提醒注意
3. **高分通过**: 无建议，直接输出

## 设计要点

1. **独立性**: Critic 不能修改上游输出，只能评价
2. **可解释**: 每项检查附带具体 detail
3. **阈值可调**: `quality_passed` 阈值通过配置文件调整
4. **Learning Loop 联动**: 频繁低分 → Learning Loop 上调 Critic 权重
