# Synthesizer Agent — 画像合成

## 文件

`byou/agents/synthesizer.py` → `SynthesizerAgent`

## 职责

整合 Extractor 和 Researcher 的输出，构建完整客户画像，输出意向评分和等级评定。

## 处理流程

```
CustomerProfile + ResearchResult
  ↓
LLM 综合分析
  ↓
{
  customer_level: "A" | "B" | "C" | "D",
  intent_score: 0.0-1.0,
  persona: {
    role: "决策者" | "影响者" | "执行者",
    style: "理性" | "感性" | "混合",
    urgency: "高" | "中" | "低",
  }
}
```

## 输入

```python
{
    "profile": CustomerProfile,      # Extractor 输出
    "research_result": dict,         # Researcher 输出
}
```

## 输出

```python
{
    "customer_level": str,           # 客户等级 (A/B/C/D)
    "intent_score": float,           # 意向评分 (0-1)
    "persona": {
        "role": str,                 # 角色分类
        "decision_power": str,       # 决策力 (high/medium/low)
        "communication_style": str,  # 沟通风格
        "pain_points": [str],        # 痛点
        "budget_range": str,         # 预算范围
        "timeline": str,             # 时间线
    },
    "insights": [str],               # 洞察列表
    "recommended_approach": str,     # 推荐切入方式
    "confidence": float,             # 综合置信度
}
```

## 客户等级评定矩阵

| 维度 | 权重 | 评分依据 |
|------|------|----------|
| 公司匹配度 | 30% | 行业 × 规模 × 融资阶段 |
| 需求迫切度 | 25% | 痛点 × 时间线 |
| 预算充足度 | 20% | 公司规模 × 行业均价 |
| 关系距离 | 15% | 人脉路径长度 |
| 竞争态势 | 10% | 竞品数量 × 亲密程度 |

## 意向评分模型

```
intent_score = Σ(维度归一化得分 × 权重)
```

## 设计要点

1. **多源融合**: 同时采信 OCR 提取和网络搜索的结果，加权合并
2. **可解释性**: 每个评分附带 reasoning 字段
3. **降级策略**: ResearchResult 缺失时，仅基于 Profile 评分
4. **缓存复用**: 同公司画像 7 天内增量更新
