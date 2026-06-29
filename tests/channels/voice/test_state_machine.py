# tests/channels/voice/test_state_machine.py
"""Tests for CallStateMachine — pure domain logic."""

import pytest

from byou.channels.voice.domain.state_machine import (
    CallStateMachine,
    InvalidTransition,
)
from byou.channels.voice.models import CallDirection, CallState


def test_initial_state():
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    assert sm.state == CallState.PENDING
    assert not sm.is_terminal


def test_normal_outbound_flow():
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    sm.initiate()
    assert sm.state == CallState.RINGING
    sm.answer()
    assert sm.state == CallState.ACTIVE
    sm.hangup()
    assert sm.state == CallState.ENDED
    assert sm.is_terminal


def test_outbound_with_hold():
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    sm.initiate()
    sm.answer()
    sm.hold()
    assert sm.state == CallState.ON_HOLD
    sm.unhold()
    assert sm.state == CallState.ACTIVE
    sm.hangup()
    assert sm.state == CallState.ENDED


def test_no_answer():
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    sm.initiate()
    assert sm.state == CallState.RINGING
    # no answer → hangup
    sm.hangup()
    assert sm.state == CallState.ENDED


def test_call_fail_any_state():
    for state in (CallState.RINGING, CallState.ACTIVE, CallState.ON_HOLD):
        sm = CallStateMachine(direction=CallDirection.OUTBOUND)
        sm._state = state  # noqa: SLF001
        sm.fail()
        assert sm.state == CallState.FAILED
        assert sm.is_terminal


def test_inbound_starts_active():
    sm = CallStateMachine(direction=CallDirection.INBOUND)
    sm.answer()  # inbound: answer directly from PENDING
    assert sm.state == CallState.ACTIVE


def test_inbound_cannot_ring():
    sm = CallStateMachine(direction=CallDirection.INBOUND)
    with pytest.raises(InvalidTransition, match="Only outbound calls can ring"):
        sm.initiate()


def test_invalid_transition():
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    # can't go from PENDING to ACTIVE without ringing
    with pytest.raises(InvalidTransition):
        sm.answer()


def test_terminal_no_transitions():
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    sm.initiate()
    sm.hangup()
    assert sm.is_terminal

    for method in [sm.answer, sm.hold, sm.unhold, sm.hangup, sm.initiate]:
        with pytest.raises(InvalidTransition):
            method()


def test_transition_table_completeness():
    """Every state should have defined allowed transitions."""
    all_states = {CallState.PENDING, CallState.RINGING, CallState.ACTIVE,
                  CallState.ON_HOLD, CallState.FAILED, CallState.ENDED}
    from byou.channels.voice.domain.state_machine import TRANSITIONS
    assert set(TRANSITIONS) == all_states, "Missing states in transition table"


def test_convenience_methods_consistency():
    """initiate()/answer()/hold()/unhold()/hangup() all produce expected target states."""
    sm = CallStateMachine(direction=CallDirection.OUTBOUND)
    sm.initiate(); assert sm.state == CallState.RINGING
    sm.answer();   assert sm.state == CallState.ACTIVE
    sm.hold();     assert sm.state == CallState.ON_HOLD
    sm.unhold();   assert sm.state == CallState.ACTIVE
    sm.hangup();   assert sm.state == CallState.ENDED
