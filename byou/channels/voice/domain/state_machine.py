# byou/channels/voice/domain/state_machine.py
"""CallStateMachine — pure domain logic for call lifecycle transitions.

No I/O, no async, no provider references. Fully testable in isolation.
"""

from __future__ import annotations

from byou.channels.voice.models import CallDirection, CallState


TRANSITIONS: dict[CallState, set[CallState]] = {
    CallState.PENDING:   {CallState.RINGING, CallState.FAILED},
    CallState.RINGING:   {CallState.ACTIVE, CallState.FAILED, CallState.ENDED},
    CallState.ACTIVE:    {CallState.ON_HOLD, CallState.FAILED, CallState.ENDED},
    CallState.ON_HOLD:   {CallState.ACTIVE, CallState.FAILED, CallState.ENDED},
    CallState.FAILED:    set(),  # terminal
    CallState.ENDED:     set(),  # terminal
}


class InvalidTransition(Exception):
    pass


class CallStateMachine:
    """Pure state machine for a single call session."""

    def __init__(self, direction: CallDirection = CallDirection.OUTBOUND) -> None:
        self.direction = direction
        self._state = CallState.PENDING

    @property
    def state(self) -> CallState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in (CallState.FAILED, CallState.ENDED)

    def transition(self, to: CallState) -> None:
        allowed = TRANSITIONS.get(self._state, set())
        if to not in allowed:
            raise InvalidTransition(
                f"Cannot transition {self._state.value} → {to.value}"
            )
        # PENDING → RINGING only for outbound; inbound starts at ACTIVE
        if self._state == CallState.PENDING and to == CallState.RINGING:
            if self.direction != CallDirection.OUTBOUND:
                raise InvalidTransition("Only outbound calls can ring")
        self._state = to

    # Convenience methods

    def initiate(self) -> None:
        self.transition(CallState.RINGING)

    def answer(self) -> None:
        if self._state == CallState.PENDING:
            if self.direction == CallDirection.INBOUND:
                self._state = CallState.ACTIVE
            else:
                raise InvalidTransition("Outbound calls must initiate (ring) before answer")
        else:
            self.transition(CallState.ACTIVE)

    def hold(self) -> None:
        self.transition(CallState.ON_HOLD)

    def unhold(self) -> None:
        self.transition(CallState.ACTIVE)

    def hangup(self) -> None:
        self.transition(CallState.ENDED)

    def fail(self) -> None:
        self.transition(CallState.FAILED)
