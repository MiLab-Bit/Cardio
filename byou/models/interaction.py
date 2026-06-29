"""
交互数据模型

定义客户交互、跟进记录等业务实体。
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class Interaction(BaseModel):
    """客户交互记录"""

    id: Optional[str] = None
    customer_name: str = Field(..., description="客户名称")
    interaction_type: str = Field(
        default="meeting",
        description="交互类型: meeting/call/email/wechat/other",
    )
    timestamp: datetime = Field(default_factory=datetime.now)
    summary: str = Field(default="", description="交互摘要")
    key_points: list[str] = Field(default_factory=list, description="关键要点")
    action_items: list[str] = Field(default_factory=list, description="待办事项")
    sentiment: Optional[str] = Field(default=None, description="客户情绪: positive/neutral/negative")
    next_follow_up: Optional[datetime] = None

    model_config = {"extra": "allow"}


class FollowUpTask(BaseModel):
    """跟进任务"""

    id: Optional[str] = None
    customer_name: str
    task_type: str = Field(default="call", description="任务类型: call/email/meeting/message")
    priority: str = Field(default="medium", description="优先级: high/medium/low")
    due_date: Optional[datetime] = None
    description: str = ""
    status: str = Field(default="pending", description="状态: pending/in_progress/done/cancelled")
    assigned_to: str = ""
    notes: str = ""

    model_config = {"extra": "allow"}


class MeetingNote(BaseModel):
    """会议纪要"""

    id: Optional[str] = None
    title: str = ""
    participants: list[str] = Field(default_factory=list)
    date: datetime = Field(default_factory=datetime.now)
    duration_minutes: int = 0
    agenda: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[dict] = Field(default_factory=list)
    raw_transcript: str = ""
    summary: str = ""
