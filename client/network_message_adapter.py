"""Translates raw wire messages (server/protocol.py's JSON dicts, as
received by client/network_client.py's poll_messages()) into typed domain
events published on an events/bus.py Bus - the network counterpart to
events/bus_bridge.py's BusBridge, which does the same job translating a
local GameEngine's own on_move_logged/on_arrival calls instead of wire JSON.

Deliberately narrow: the only thing this class knows is "message.get('type')
-> which dataclass, built from which fields". It never decides what a
DisconnectCountdownEvent or a MoveRejectedEvent *means* to anyone downstream
(see client/game_view_state.py's StatusBannerState for that) - the same
split SoundCues/GameAnimationCues already have from whichever event reaches
them, kept here on the producing side too rather than only the consuming one.

The full-board "pieces" snapshot broadcast is deliberately not handled here,
unlike every message type below - it isn't a discrete moment something
happened, it's the server's whole authoritative state as of this tick, so
client/game_view_state.py's GameViewState applies it to its own snapshot/
panel_state directly instead of through an event (see its own apply_message).
"""

from dataclasses import dataclass
from typing import Optional

from events.bus import Bus
from events.game_events import GameEndedEvent, RemoteCaptureEvent
from model.game_state import MoveLoggedEvent

# Network-only events - nothing about a local game (play.py/game_builder.py)
# ever produces or subscribes to these, unlike RemoteCaptureEvent/
# GameEndedEvent (events/game_events.py), which SoundCues/GameAnimationCues
# already react to for both local and networked play.
@dataclass(frozen=True)
class DisconnectCountdownEvent:
    seconds_remaining: int


@dataclass(frozen=True)
class MoveRejectedEvent:
    reason: str


class NetworkMessageAdapter:
    def __init__(self, bus: Bus):
        self._bus = bus
        self._event_factories = {
            "move_logged": self._move_logged_event,
            "capture": self._capture_event,
            "game_over": self._game_over_event,
            "disconnect_countdown": self._disconnect_countdown_event,
            "ack": self._ack_event,
        }

    # Silently ignores any message type it has no factory for - the same
    # "unknown type is a no-op" behavior client/game_view_state.py's
    # apply_message had before this class existed.
    def apply(self, message: dict) -> None:
        factory = self._event_factories.get(message.get("type"))
        if factory is None:
            return
        event = factory(message)
        if event is not None:
            self._bus.publish(event)

    def _move_logged_event(self, message: dict) -> MoveLoggedEvent:
        return MoveLoggedEvent(
            color="",
            kind="",
            source=None,
            destination=None,
            is_capture=False,
            is_jump=message["is_jump"],
            elapsed_ms=0,
            piece_id="",
        )

    def _capture_event(self, _message: dict) -> RemoteCaptureEvent:
        return RemoteCaptureEvent()

    def _game_over_event(self, message: dict) -> GameEndedEvent:
        print(f"Game over. New ratings: {message['ratings']}")
        # arrival=None - unlike every other GameEndedEvent, there's no
        # ArrivalEvent behind a networked game-over at all (see
        # server/session.py's resign(), a disconnect timeout rather than a
        # king-capture ArrivalEvent), and neither SoundCues nor
        # GameAnimationCues ever reads this field anyway.
        return GameEndedEvent(arrival=None)

    def _disconnect_countdown_event(self, message: dict) -> DisconnectCountdownEvent:
        return DisconnectCountdownEvent(seconds_remaining=message["seconds_remaining"])

    # None (no event) when the move was accepted - there's nothing for
    # StatusBannerState to react to, the same as apply() silently
    # discarding a message type it has no factory for at all.
    def _ack_event(self, message: dict) -> Optional[MoveRejectedEvent]:
        if message.get("accepted"):
            return None
        return MoveRejectedEvent(reason=message.get("reason"))
