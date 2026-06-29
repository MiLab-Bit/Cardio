# 数据模型设计

## 文件

- `byou/models/customer.py` — 客户相关模型
- `byou/models/interaction.py` — 交互相关模型
- `byou/models/strategy.py` — 策略相关模型

## 模型总览

```
CustomerProfile          (核心实体 — 客户画像)
PipelineContext          (Orchestrator — Pipeline 执行上下文)
ResearchResult           (Researcher — 背调结果)

Interaction              (交互记录)
FollowUpTask             (跟进任务)
MeetingNote              (会议记录)

BDStrategy               (策略输出)
TalkingPoint             (洽谈要点)
FollowUpPlan             (跟进计划)
BDRisk                   (BD 风险)
```

## CustomerProfile

```python
class CustomerProfile(BaseModel):
    name: str = ""
    title: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    wechat: str = ""
    department: str = ""
    address: str = ""
    source: str = "card"      # card / manual / import
    confidence: float = 0.0    # 提取置信度
    extra: dict = {}           # 扩展字段
```

## PipelineContext

```python
class PipelineContext(BaseModel):
    id: Optional[str]          # Pipeline 执行 ID
    started_at: datetime
    completed_at: Optional[datetime]

    # 输入
    card_image_path: Optional[str]
    audio_file_path: Optional[str]
    extra_context: dict

    # 阶段输出
    raw_extraction: dict
    raw_text: str
    profile: Optional[CustomerProfile]
    research_result: dict
    synthesis_result: dict
    strategy_result: dict
    critique_result: dict

    # 评分
    intent_score: Optional[float]
    customer_level: Optional[str]
    trust_score: Optional[float]
    quality_passed: Optional[bool]

    # 异常
    risk_alerts: list[str]
    errors: list[str]

    def get_summary() -> dict  # 生成执行摘要
```

## BDStrategy

```python
class BDStrategy(BaseModel):
    confidence_level: float = 0.7
    version: str = "1.0"
    customer_analysis: str = ""
    pain_points: list[str]
    opportunities: list[str]
    talking_points: list[TalkingPoint]
    follow_up_plan: Optional[FollowUpPlan]
    risks: list[BDRisk]
    recommended_actions: list[str]
    competitive_advantage: str = ""
    extra_notes: str = ""

class TalkingPoint(BaseModel):
    angle: str = ""
    script: str = ""
    key_message: str = ""
    supporting_data: str = ""
    priority: int = 1
    objection_handling: str = ""

class FollowUpPlan(BaseModel):
    timing: str = ""
    channel: str = "wechat"
    frequency: str = "weekly"
    priority: str = "medium"
    checkpoints: list[str]

class BDRisk(BaseModel):
    type: str = ""
    description: str = ""
    probability: str = "medium"
    impact: str = "medium"
    severity: str = "medium"
    mitigation: str = ""
```

## Interaction

```python
class Interaction(BaseModel):
    customer_name: str
    company: str = ""
    interaction_type: str = "call"
    timestamp: datetime
    summary: str = ""
    sentiment: str = "neutral"
    next_steps: str = ""

class FollowUpTask(BaseModel):
    customer_name: str
    task_type: str = "call"
    priority: str = "medium"
    due_date: Optional[datetime]
    status: str = "pending"
    notes: str = ""

class MeetingNote(BaseModel):
    title: str
    attendees: list[str]
    duration_minutes: int = 30
    key_points: list[str]
    action_items: list[str]
    raw_transcript: str = ""
```

## Pydantic 配置

所有模型使用 **Pydantic v2** + `model_config = {"extra": "allow"}` 允许扩展字段。
