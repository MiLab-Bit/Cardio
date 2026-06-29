# Pipeline 流程

## 一、完整 Pipeline

```
  ┌─────────┐
  │  输入   │  Card Image (.jpg/.png) + Audio (.mp3/.wav)
  └────┬────┘
       │
  ┌────▼────┐  Q1: 这是谁？什么公司？说了什么？
  │Extractor│  OCR 名片 + ASR 语音 → {profile, raw_text, key_points}
  └────┬────┘
       │
  ┌────▼────┐  Q2: 这家公司什么背景？这个人什么来头？
  │Researcher│  多源搜索 + 知识图谱 → {company_info, industry, competitors}
  └────┬────┘
       │
  ┌────▼────┐  Q3: 综合来看，这是什么层级的客户？
  │Synthesizer│  画像建模 → {customer_level, intent_score, insights}
  └────┬────┘
       │
  ┌────▼────┐  Q4: 怎么拿下？什么策略最有效？
  │Strategist│  策略生成 → {talking_points, follow_up_plan, risks}
  └────┬────┘
       │
  ┌────▼────┐  Q5: 策略靠谱吗？有遗漏吗？
  │  Critic  │  质量审核 → {trust_score, quality_passed, suggestions}
  └────┬────┘
       │
  ┌────▼────┐
  │  输出   │  PipelineContext (含完整链路数据)
  └─────────┘
```

## 二、各阶段输入输出

| 阶段 | Agent | 输入 | 输出 |
|------|-------|------|------|
| 1. 提取 | Extractor | card_image_path, audio_file_path | profile, raw_text, key_points |
| 2. 背调 | Researcher | company_name, person_name, profile | company_info, industry_analysis, competitors |
| 3. 画像 | Synthesizer | profile, research_result | customer_level, intent_score, persona |
| 4. 策略 | Strategist | profile, persona, research | talking_points, follow_up_plan, risks |
| 5. 质检 | Critic | 全部上游输出 | trust_score, quality_passed, suggestions |

## 三、数据流转

所有阶段共享 **PipelineContext** 对象：

```python
class PipelineContext(BaseModel):
    # 输入
    card_image_path: Optional[str]
    audio_file_path: Optional[str]
    extra_context: dict

    # 阶段输出（逐阶段填充）
    raw_extraction: dict      # Extractor 输出
    profile: CustomerProfile  # 结构化客户信息
    research_result: dict     # Researcher 输出
    synthesis_result: dict    # Synthesizer 输出
    strategy_result: dict     # Strategist 输出
    critique_result: dict     # Critic 输出

    # 评分
    intent_score: Optional[float]
    customer_level: Optional[str]
    trust_score: Optional[float]
    quality_passed: Optional[bool]

    # 异常
    risk_alerts: list[str]
    errors: list[str]
```

## 四、进度回调

Orchestrator 通过 `on_progress(stage, data)` 回调暴露 Pipeline 进度：

```python
# 阶段名称
"pipeline_start" → "extraction" → "extraction_done"
→ "research" → "research_done"
→ "synthesis" → "synthesis_done"
→ "strategy" → "strategy_done"
→ "critique" → "critique_done"
→ "pipeline_complete" / "pipeline_error"
```

## 五、错误处理

- 单阶段失败不阻断 Pipeline — 记录 `errors`，继续执行后续可用阶段
- 关键阶段（Extractor）失败 → Pipeline 提前终止
- 非关键阶段（Strategist）失败 → 跳过后继续
