# tests/channels/voice/test_event_translator.py
"""Tests for VoiceEventTranslator — Dograh payload → ChannelEvent."""

from byou.channels.voice.adapters.event_translator import VoiceEventTranslator
from byou.channels.voice.models import CallDirection, CallState, Speaker


translator = VoiceEventTranslator()


# ══════════════════════════════════════════════════════════
# Dograh event mapping
# ══════════════════════════════════════════════════════════

DOGRAH_CALL_ID = "dograh_call_abc123"
SESSION_ID = "sess_test001"


def test_translate_call_initiated():
    event = translator.translate_dograh({
        "event": "call.initiated",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "direction": "outbound",
    })
    assert event.event_type == "call_started"
    assert event.provider_ref == DOGRAH_CALL_ID
    assert event.direction == CallDirection.OUTBOUND
    assert event.session is not None
    assert event.session.state == CallState.RINGING
    assert event.turn is None


def test_translate_call_answered():
    event = translator.translate_dograh({
        "event": "call.answered",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "direction": "outbound",
    })
    assert event.event_type == "call_answered"
    assert event.session.state == CallState.ACTIVE


def test_translate_call_hangup():
    event = translator.translate_dograh({
        "event": "call.hangup",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "direction": "outbound",
    })
    assert event.event_type == "call_ended"
    assert event.session.state == CallState.ENDED


def test_translate_call_error():
    event = translator.translate_dograh({
        "event": "call.error",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "direction": "outbound",
        "error": "NETWORK_ERROR",
    })
    assert event.event_type == "call_failed"
    assert event.session.state == CallState.FAILED


def test_translate_user_speech_end():
    event = translator.translate_dograh({
        "event": "user.speech.end",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "turn_id": "turn_003",
        "turn_sequence": 3,
        "transcript": "我想了解一下你们的价格方案",
        "duration_ms": 3200,
        "audio_url": "https://storage.dograh.com/audio/chunk_003.wav",
    })
    assert event.event_type == "user_turn"
    assert event.turn is not None
    assert event.turn.text == "我想了解一下你们的价格方案"
    assert event.turn.speaker == Speaker.USER
    assert event.turn.sequence == 3
    assert event.turn.duration_ms == 3200
    assert event.turn.audio_chunk_ref == "https://storage.dograh.com/audio/chunk_003.wav"


def test_translate_transfer_request():
    event = translator.translate_dograh({
        "event": "call.transfer.request",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "direction": "outbound",
        "reason": "user_request",
    })
    assert event.event_type == "transfer_requested"


def test_translate_unknown_event():
    event = translator.translate_dograh({
        "event": "call.custom.metric",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "direction": "outbound",
        "latency_ms": 150,
    })
    assert event.event_type == "unknown"
    # Still produces a valid ChannelEvent with raw_meta
    assert event.session_id == SESSION_ID
    assert event.raw_meta


# ══════════════════════════════════════════════════════════
# Reverse translation: AgentTurn → Dograh instruction
# ══════════════════════════════════════════════════════════

def test_to_dograh_message():
    instruction = translator.to_dograh_message(SESSION_ID, {
        "text": "您好，我是XX公司的AI助手",
        "emotion": "friendly",
        "metadata": {"campaign": "q3_outreach"},
    })
    assert instruction["action"] == "speak"
    assert instruction["call_id"] == SESSION_ID
    assert instruction["text"] == "您好，我是XX公司的AI助手"
    assert instruction["emotion"] == "friendly"


def test_to_dograh_handoff():
    instruction = translator.to_dograh_handoff({
        "session_id": SESSION_ID,
        "transfer_target": "support",
        "handoff_notes": "用户要求技术专家解答",
    })
    assert instruction["action"] == "transfer"
    assert instruction["target"] == "support"


# ══════════════════════════════════════════════════════════
# Generic translator
# ══════════════════════════════════════════════════════════

def test_translate_generic():
    event = translator.translate_generic(
        {"event_type": "call.connected", "call_id": "x_001"},
        provider="some-future-provider",
    )
    assert event.event_type == "call.connected"
    assert event.raw_meta["_provider"] == "some-future-provider"


# ══════════════════════════════════════════════════════════
# Provider payload isolation
# ══════════════════════════════════════════════════════════

def test_provider_audio_data_not_leaked():
    """Raw audio data must NOT enter ChannelEvent."""
    event = translator.translate_dograh({
        "event": "user.speech.end",
        "call_id": DOGRAH_CALL_ID,
        "session_id": SESSION_ID,
        "transcript": "测试",
        "audio_data": "AAAA...really long base64...==",
        "audio_base64": "BBBB...another giant blob...==",
    })
    assert "audio_data" not in event.raw_meta
    assert "audio_base64" not in event.raw_meta
    assert event.turn.text == "测试"  # text still comes through
