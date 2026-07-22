"""State a networked game window (play_online.py) accumulates from the
server's own broadcasts - the latest board/panel snapshot, this client's
local sound/animation Bus, and the two transient status banners
(disconnect countdown, a rejected move) - kept as its own class so the
message-dispatch logic (apply_message) is unit-testable without a real
GameWindow/canvas/renderer, the same way client/network_controller.py's
click/jump logic already is.

apply_message's only job is translating a raw wire message into a typed
domain event and publishing it on self.bus (events/bus.py) - it never
mutates view state itself. Every subscriber below (SoundCues,
GameAnimationCues, StatusBannerCues) reacts to whichever event types it
cares about without apply_message needing to know who's listening, the same
Pub/Sub split game_builder.py's build_app already uses for local play
(events/bus_bridge.py publishing GameEngine's own on_move_logged/on_arrival
calls onto a Bus). Before this, apply_message dispatched through a private
message_type -> bound-method table and had disconnect_countdown/ack write
straight into this object's own fields - a hand-rolled, string-keyed
Subject/Observer that only this class could ever add a listener to.

There's no GameEngine here to publish MoveLoggedEvent/ArrivalEvent itself
(unlike play.py), so apply_message reconstructs minimal stand-ins for
those two events straight from the server's own "move_logged"/"capture"
wire messages (see server/session.py's drain_wire_events, buffered off the
server's real GameEngine-fed bus) - server-authoritative facts, not a guess
reconstructed from move-log notation text. The fields neither SoundCues nor
GameAnimationCues ever reads (piece identity, board positions, the real
captured Piece) are left as placeholders - the wire never carries them, and
nothing downstream looks at them.
"""

import time
from dataclasses import dataclass
from typing import Optional

from events.bus import Bus
from events.game_animations import GameAnimationCues
from events.game_events import GameEndedEvent, GameStartedEvent
from events.sound import SoundCues
from model.game_state import ArrivalEvent, GameSnapshot, MoveLoggedEvent
from server.protocol import PanelState, snapshot_from_json

# A stand-in for the real captured Piece SoundCues/GameAnimationCues never
# actually get here (see this module's own docstring) - ArrivalEvent's
# captured_piece is only ever tested for "is this None or not" by either
# subscriber, never read into, so any non-None object satisfies that check.
_CAPTURED_PIECE_PLACEHOLDER = object()


# The three event types below exist only for this module's own wire
# messages (disconnect_countdown/ack/the periodic full snapshot) - unlike
# MoveLoggedEvent/ArrivalEvent (model/game_state.py) or GameStartedEvent/
# GameEndedEvent (events/game_events.py), nothing outside a networked game
# ever produces or subscribes to them, so they're kept next to their one
# publisher (apply_message) and one subscriber (StatusBannerCues) instead.
@dataclass(frozen=True)
class DisconnectCountdownEvent:
    seconds_remaining: int


@dataclass(frozen=True)
class MoveRejectedEvent:
    reason: str


@dataclass(frozen=True)
class SnapshotAppliedEvent:
    pass


# How long a rejected move/jump's message stays on screen - the ack itself
# (unlike disconnect_countdown) is a one-off reply, not a standing state
# the server keeps re-broadcasting, so there's no "still true" signal to
# clear it on; it just times out instead.
ILLEGAL_MOVE_MESSAGE_S = 2.0


# Owns the single status-banner slot play_online.py reads (GameViewState.
# status_message delegates here) - a Bus subscriber like SoundCues/
# GameAnimationCues, so it (and only it) knows how a disconnect countdown
# and a rejected move combine into one line of text.
class StatusBannerCues:
    def __init__(self, bus: Bus):
        self.disconnect_countdown_text: Optional[str] = None
        self.illegal_move_text: Optional[str] = None
        self._illegal_move_expires_at = 0.0
        self._saw_snapshot_this_batch = False
        self._saw_countdown_this_batch = False

        bus.subscribe(DisconnectCountdownEvent, self._on_disconnect_countdown)
        bus.subscribe(MoveRejectedEvent, self._on_move_rejected)
        bus.subscribe(SnapshotAppliedEvent, self._on_snapshot_applied)

    # Called once before draining a poll_messages() batch - see end_batch,
    # which reacts to what this batch's events did (or didn't) say.
    def begin_batch(self) -> None:
        self._saw_snapshot_this_batch = False
        self._saw_countdown_this_batch = False

    def _on_disconnect_countdown(self, event: DisconnectCountdownEvent) -> None:
        self.disconnect_countdown_text = (
            f"Opponent disconnected - resigning in {event.seconds_remaining}s unless they return"
        )
        self._saw_countdown_this_batch = True

    def _on_move_rejected(self, event: MoveRejectedEvent) -> None:
        self.illegal_move_text = f"Illegal move: {event.reason}"
        self._illegal_move_expires_at = time.monotonic() + ILLEGAL_MOVE_MESSAGE_S

    def _on_snapshot_applied(self, _event: SnapshotAppliedEvent) -> None:
        self._saw_snapshot_this_batch = True

    # Called once after a poll_messages() batch has been fully applied -
    # reacts to facts about the whole batch (see the two _saw_*_this_batch
    # flags), not to any single event, so this can't live in either
    # subscriber callback above.
    def end_batch(self) -> None:
        # A tick that broadcast a snapshot but no accompanying
        # disconnect_countdown means the opponent's seat is no longer
        # disconnected (see server/ws_server.py's _advance_game, which only
        # ever sends the countdown while is_disconnected(seat)) - clear the
        # stale banner rather than leaving last tick's message on screen
        # forever once they reconnect.
        if self._saw_snapshot_this_batch and not self._saw_countdown_this_batch:
            self.disconnect_countdown_text = None

        if self.illegal_move_text is not None and time.monotonic() >= self._illegal_move_expires_at:
            self.illegal_move_text = None

    @property
    def status_message(self) -> Optional[str]:
        # disconnect_countdown_text wins the single status-message slot
        # when both are live - it reflects a standing fact the opponent is
        # waiting on, not a transient one-off like a rejected move.
        return self.disconnect_countdown_text or self.illegal_move_text


class GameViewState:
    def __init__(self, first_snapshot_payload: dict):
        self.snapshot: GameSnapshot = snapshot_from_json(first_snapshot_payload)
        self.panel_state = PanelState()
        self.panel_state.update_from_json(first_snapshot_payload)

        # This client's own local Bus - the network counterpart to
        # game_builder.py's build_app wiring the same subscribers to a
        # GameEngine-fed Bus for local play (see this module's own docstring).
        self.bus = Bus()
        SoundCues(self.bus)
        GameAnimationCues(self.bus)
        self.status_banner = StatusBannerCues(self.bus)
        self.bus.publish(GameStartedEvent())

        # message.get("type") -> raw wire message -> domain event, the one
        # thing apply_message needs per-instance state for (none, actually -
        # every factory below is pure - but kept as a bound-method dict
        # anyway so a message type unknown here is a silent no-op lookup
        # miss, same as before).
        self._event_factories = {
            "move_logged": self._move_logged_event,
            "capture": self._capture_event,
            "game_over": self._game_over_event,
            "disconnect_countdown": self._disconnect_countdown_event,
            "ack": self._ack_event,
        }

    def begin_batch(self) -> None:
        self.status_banner.begin_batch()

    # Translates one raw wire message into a domain event and publishes it
    # on self.bus - never mutates view state directly (see this module's own
    # docstring for why: every subscriber above owns its own reaction).
    def apply_message(self, message: dict) -> None:
        if "pieces" in message:
            self.snapshot = snapshot_from_json(message)
            self.panel_state.update_from_json(message)
            self.bus.publish(SnapshotAppliedEvent())
            return

        factory = self._event_factories.get(message.get("type"))
        if factory is None:
            return
        event = factory(message)
        if event is not None:
            self.bus.publish(event)

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

    def _capture_event(self, _message: dict) -> ArrivalEvent:
        return ArrivalEvent(piece=None, captured_piece=_CAPTURED_PIECE_PLACEHOLDER)

    def _game_over_event(self, message: dict) -> GameEndedEvent:
        print(f"Game over. New ratings: {message['ratings']}")
        # arrival=None - unlike every other GameEndedEvent, there's no
        # ArrivalEvent behind a networked game-over at all (see
        # server/session.py's resign(), a disconnect timeout rather
        # than a king-capture ArrivalEvent), and neither SoundCues nor
        # GameAnimationCues ever reads this field anyway (see this
        # module's own docstring).
        return GameEndedEvent(arrival=None)

    def _disconnect_countdown_event(self, message: dict) -> DisconnectCountdownEvent:
        return DisconnectCountdownEvent(seconds_remaining=message["seconds_remaining"])

    # None (no event) when the move was accepted - there's nothing for
    # StatusBannerCues to react to, the same as apply_message silently
    # discarding a message type it has no factory for at all.
    def _ack_event(self, message: dict) -> Optional[MoveRejectedEvent]:
        if message.get("accepted"):
            return None
        return MoveRejectedEvent(reason=message.get("reason"))

    def end_batch(self) -> None:
        self.status_banner.end_batch()

    @property
    def status_message(self) -> Optional[str]:
        return self.status_banner.status_message
