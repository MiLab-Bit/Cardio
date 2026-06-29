# Strategist Agent — BD 策略生成

## 文件

`byou/agents/strategist.py` → `StrategistAgent`

## 职责

基于客户画像和背调结果，生成可执行的 BD 行动策略。

## 处理流程

```
客户画像 + 人设(Persona) + 行业分析
  ↓
LLM 策略推理
  ↓
{
  talking_points: [TalkingPoint],      # 洽谈要点
  follow_up_plan: FollowUpPlan,        # 跟进计划
  risks: [BDRisk],                     # 风险清单
  recommended_actions: [str],          # 推荐动作
}
```

## 输入

```python
{
    "profile": CustomerProfile,
    "persona": dict,            # Synthesizer 输出
    "research_result": dict,    # Researcher 输出
}
```

## 输出

```python
{
    "talking_points": [
        {
            "angle": str,        # 切入角度
            "script": str,       # 话术脚本
            "key_message": str,  # 核心信息
            "supporting_data": str, # 支撑数据
            "priority": int,     # 优先级 (1=最高)
        }
    ],
    "follow_up_plan": {
        "timing": str,           # 跟进时机
        "channel": str,          # 沟通渠道 (phone/email/wechat/visit)
        "frequency": str,        # 跟进频率
        "priority": str,         # 整体优先级
        "checkpoints": [str],    # 里程碑
    },
    "risks": [
        {
            "type": str,         # 风险类型
            "description": str,  # 描述
            "probability": str,  # 概率
            "impact": str,       # 影响
            "severity": str,     # 严重程度 (high/medium/low)
            "mitigation": str,   # 缓解措施
        }
    ],
    "recommended_actions": [str],
    "competitive_advantage": str,
}
```

## 风险类型

| 类型 | 示例 |
|------|------|
| 竞争风险 | 竞品 X 已接触客户 |
| 预算风险 | 客户预算低于方案价格 |
| 决策风险 | 对接人不是最终决策者 |
| 时间风险 | 客户采购周期 > 3 个月 |
| 关系风险 | 无内部引荐人 |
| 合规风险 | 行业合规要求高 |

## Talking Point 生成规则

1. **每个 Talking Point 对应一个核心痛点**
2. **使用客户行业术语**
3. **包含量化数据支撑**（如 "可降低 30% 运维成本"）
4. **优先级排序**: P1 对应最大痛点

## 设计要点

1. **模板驱动**: 基础话术模板 + LLM 个性化填充
2. **知识库增强**: 从历史成功案例中检索相似话术
3. **风险闭环**: 识别风险时同步生成 mitigation
