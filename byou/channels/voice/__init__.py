# byou/channels/voice/__init__.py
"""Voice channel adapter — implements ChannelPort for telephony.

Layers:
  domain/       — CallStateMachine (pure, no I/O)
  application/  — coordinator, policy, post-call orchestration
  adapters/     — provider bridges (dograh_bridge.py, event_translator.py)
  assembly.py   — DI wiring: Protocol adapters → real Byou Core services
  webhooks.py   — HTTP entrypoint (if needed)
"""

from byou.channels.voice.models import (
    AgentTurn,
    AudioFeatures,
    CallDirection,
    CallOutcome,
    CallSession,
    CallState,
    CallTurn,
    ChannelCapability,
    ChannelEvent,
    ChannelKind,
    FollowUpAction,
    HandoffRequest,
    LeadContext,
    PostCallReport,
    PreCallAudit,
    PreCallPackage,
    QualificationSignal,
    TalkingPoint,
)
from byou.channels.voice.ports import (
    ApprovalGateway,
    ChannelPort,
    CRMGateway,
    DurableExecutionGateway,
    HandoffPort,
    InboundChannelEventPort,
    MemoryGateway,
    OutboundChannelPort,
    PostCallAnalysisPort,
    SLMGateway,
    TranscriptIngestionPort,
)

__all__ = [
    # models
    "AgentTurn",
    "AudioFeatures",
    "CallDirection",
    "CallOutcome",
    "CallSession",
    "CallState",
    "CallTurn",
    "ChannelCapability",
    "ChannelEvent",
    "ChannelKind",
    "FollowUpAction",
    "HandoffRequest",
    "LeadContext",
    "PostCallReport",
    "PreCallAudit",
    "PreCallPackage",
    "QualificationSignal",
    "TalkingPoint",
    # ports
    "ApprovalGateway",
    "ChannelPort",
    "CRMGateway",
    "DurableExecutionGateway",
    "HandoffPort",
    "InboundChannelEventPort",
    "MemoryGateway",
    "OutboundChannelPort",
    "PostCallAnalysisPort",
    "SLMGateway",
    "TranscriptIngestionPort",
]
