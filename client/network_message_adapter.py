"""Translates already-decoded wire messages (typed items, as put on
client/network_client.py's queue by its own _decode_incoming - see that
module's own docstring) into typed domain events published on an
events/bus.py Bus - the network counterpart to events/bus_bridge.py's
BusBridge, which does the same job translating a local GameEngine's own
on_move_logged/on_arrival calls instead of wire JSON.

Decoding a raw dict into its own protocol.lobby_messages/protocol.game_messages
dataclass (protocol/registry.py's message_from_dict) already happened before
apply() ever sees a message - client/network_client.py's own receive loop is
the one place that runs, so apply() never re-lists a message's fields by
hand; this class only ever decides which *typed* wire message translates to
which Bus event, if any. It never decides what a DisconnectCountdownEvent or
a MoveRejectedEvent *means* to anyone downstream (see
client/game_view_state.py's StatusBannerState for that) - the same split
SoundCues/GameAnimationCues already have from whichever event reaches them,
kept here on the producing side too rather than only the consuming one.

The full-board "pieces" snapshot broadcast is deliberately not handled here,
unlike every message type below - it isn't a discrete moment something
happened, it's the server's whole authoritative state as of this tick, so
client/game_view_state.py's GameViewState applies it to its own snapshot/
panel_state directly instead of through an event (see its own apply_message).
"""

from dataclasses import dataclass
from typing import Optional

from events.bus import Bus
from events.game_events import GameEndedEvent, RemoteCaptureEvent, RemoteMoveEvent
from protocol.game_messages import (
    AckMessage,
    CaptureMessage,
    DisconnectCountdownMessage,
    GameOverMessage,
    MoveLoggedMessage,
)

# Network-only events - nothing about a local game (play.py/game_builder.py)
# ever produces or subscribes to these, unlike RemoteCaptureEvent/
# RemoteMoveEvent/GameEndedEvent (events/game_events.py), which SoundCues/
# GameAnimationCues already react to for both local and networked play.
@dataclass(frozen=True)
class DisconnectCountdownEvent:
    seconds_remaining: int


@dataclass(frozen=True)
class MoveRejectedEvent:
    reason: str


class NetworkMessageAdapter:
    def __init__(self, bus: Bus):
        self._bus = bus
        # Keyed by the *decoded* wire dataclass's own type (see
        # protocol/registry.py's message_from_dict), not the raw "type" string -
        # decoding a message's own fields is message_from_dict's job alone;
        # this table only ever decides which Bus event (if any) a given
        # wire message translates to.
        self._event_factories = {
            MoveLoggedMessage: self._move_logged_event,
            CaptureMessage: self._capture_event,
            GameOverMessage: self._game_over_event,
            DisconnectCountdownMessage: self._disconnect_countdown_event,
            AckMessage: self._ack_event,
        }

    # Silently ignores any message this has no factory for - the same
    # "unknown type is a no-op" behavior client/game_view_state.py's
    # apply_message had before this class existed. Covers both a message
    # type client/network_client.py's own decode step didn't recognize at
    # all (still a raw dict by the time it gets here) and one that decoded
    # fine but this class has no translation for.
    def apply(self, message: object) -> None:
        factory = self._event_factories.get(type(message))
        if factory is None:
            return
        event = factory(message)
        if event is not None:
            self._bus.publish(event)

    def _move_logged_event(self, message: MoveLoggedMessage) -> RemoteMoveEvent:
        return RemoteMoveEvent(is_jump=message.is_jump)

    def _capture_event(self, _message: CaptureMessage) -> RemoteCaptureEvent:
        return RemoteCaptureEvent()

    def _game_over_event(self, message: GameOverMessage) -> GameEndedEvent:
        # arrival=None - unlike every other GameEndedEvent, there's no
        # ArrivalEvent behind a networked game-over at all (see
        # server/session.py's resign(), a disconnect timeout rather than a
        # king-capture ArrivalEvent), and neither SoundCues nor
        # GameAnimationCues ever reads this field anyway. new_ratings is the
        # one field a networked game-over actually carries - see
        # events/game_events.py's own docstring on it.
        return GameEndedEvent(arrival=None, new_ratings=message.ratings)

    def _disconnect_countdown_event(self, message: DisconnectCountdownMessage) -> DisconnectCountdownEvent:
        return DisconnectCountdownEvent(seconds_remaining=message.seconds_remaining)

    # None (no event) when the move was accepted - there's nothing for
    # StatusBannerState to react to, the same as apply() silently
    # discarding a message type it has no factory for at all.
    def _ack_event(self, message: AckMessage) -> Optional[MoveRejectedEvent]:
        if message.accepted:
            return None
        return MoveRejectedEvent(reason=message.reason)
