# tests/channels/voice/test_models.py
"""Tests for voice channel canonical models."""

import pytest

from byou.channels.voice.models import (
    AudioFeatures,
    CallDirection,
    CallOutcome,
    CallSession,
    CallState,
    CallTurn,
    ChannelEvent,
    ChannelKind,
    FollowUpAction,
    FollowUpStatus,
    HandoffRequest,
    LeadContext,
    PostCallReport,
    PreCallAudit,
    PreCallPackage,
    QualificationSignal,
    Speaker,
    TalkingPoint,
    TechnicalOutcome,
)


# ══════════════════════════════════════════════════════════
# Model validation tests
# ══════════════════════════════════════════════════════════

def test_lead_context_minimal():
    ctx = LeadContext(
        lead_id="lead_001",
        company_name="Acme Corp",
        contact_name="张三",
        phone="+8613800000000",
    )
    assert ctx.lead_id == "lead_001"
    assert ctx.company_intel == {}
    assert ctx.crm_stage is None


def test_lead_context_full():
    ctx = LeadContext(
        lead_id="lead_002",
        company_name="Beta Inc",
        contact_name="李四",
        contact_title="CTO",
        phone="+8613900000000",
        company_intel={"industry": "AI", "employees": 200},
        crm_stage="qualified",
        campaign_id="camp_2026_q3",
    )
    assert ctx.crm_stage == "qualified"
    assert ctx.company_intel["industry"] == "AI"


def test_pre_call_package():
    pkg = PreCallPackage(
        lead=LeadContext(
            lead_id="lead_003",
            company_name="Gamma",
            contact_name="王五",
            phone="+8614000000000",
        ),
        call_objective="初次联系",
        talking_points=[
            TalkingPoint(angle="产品优势", script="我们的产品...", key_message="降本增效"),
        ],
        objection_handling={"价格太高": "我们提供灵活套餐"},
        pre_call_audit=PreCallAudit(risk_level="low"),
        risk_level="low",
        requires_approval=False,
    )
    assert pkg.risk_level == "low"
    assert not pkg.requires_approval
    assert len(pkg.talking_points) == 1


def test_call_session_creation():
    session = CallSession(
        session_id="sess_001",
        lead_id="lead_001",
        channel=ChannelKind.VOICE,
        direction=CallDirection.OUTBOUND,
        state=CallState.PENDING,
    )
    assert session.state == CallState.PENDING
    assert session.turn_count == 0
    assert session.provider_ref is None


def test_call_turn():
    turn = CallTurn(
        turn_id="turn_001",
        session_id="sess_001",
        sequence=1,
        speaker=Speaker.USER,
        text="你好，我想了解一下你们的产品",
        audio_features=AudioFeatures(emotion="neutral"),
    )
    assert turn.speaker == Speaker.USER
    assert turn.text.startswith("你好")
    assert turn.audio_features.emotion == "neutral"


def test_qualification_signal():
    sig = QualificationSignal(
        session_id="sess_001",
        turn_id="turn_005",
        signal_type="budget_mention",
        raw_text="我们的预算是50万左右",
        confidence=0.85,
        extracted_value="50万",
        is_positive=True,
        bant_dimension="budget",
    )
    assert sig.signal_type == "budget_mention"
    assert sig.is_positive
    assert sig.confidence == 0.85


def test_handoff_request():
    req = HandoffRequest(
        session_id="sess_001",
        reason="user_request",
        context="用户要求转接技术专家",
    )
    assert req.reason == "user_request"
    assert not req.approved  # not yet evaluated


def test_call_outcome():
    outcome = CallOutcome(
        session_id="sess_001",
        lead_id="lead_001",
        technical_outcome=TechnicalOutcome.COMPLETED,
        business_outcome="qualified",
        intent_score=0.75,
    )
    assert outcome.intent_score == 0.75


def test_post_call_report():
    report = PostCallReport(
        session_id="sess_001",
        lead_id="lead_001",
        summary="成功建立联系，客户对产品X感兴趣",
        qualification_signals=[],
    )
    assert report.summary
    assert report.quality_score == 0.5


def test_follow_up_action():
    fa = FollowUpAction(
        action_id="fa_001",
        session_id="sess_001",
        lead_id="lead_001",
        action_type="crm_task",
        priority="high",
        payload={"task": "follow_up", "notes": "3天后回访"},
    )
    assert fa.status == FollowUpStatus.PENDING
    assert fa.priority == "high"


# ══════════════════════════════════════════════════════════
# ChannelEvent tests
# ══════════════════════════════════════════════════════════

def test_channel_event_user_turn():
    turn = CallTurn(
        turn_id="turn_001",
        session_id="sess_001",
        sequence=1,
        speaker=Speaker.USER,
        text="你好",
    )
    event = ChannelEvent(
        session_id="sess_001",
        event_type="user_turn",
        turn=turn,
    )
    assert event.event_type == "user_turn"
    assert event.turn.text == "你好"


def test_channel_event_extra_fields_blocked():
    """ChannelEvent should reject unknown fields (extra='forbid')."""
    with pytest.raises(Exception):
        ChannelEvent(
            session_id="sess_001",
            event_type="user_turn",
            twilio_call_sid="CA123",  # provider field leaking in
        )
