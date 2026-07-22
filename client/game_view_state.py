"""State a networked game window (play_online.py) accumulates from the
server's own broadcasts - the latest board/panel snapshot, this client's
local sound/animation Bus, and the single status banner (disconnect
countdown, a rejected move) - kept as its own class so the message-handling
logic (apply_message) is unit-testable without a real GameWindow/canvas/
renderer, the same way client/network_controller.py's click/jump logic
already is.

apply_message's own job is now narrow: apply the periodic full-board
snapshot directly (there's no discrete "event" to publish for a continuous
state broadcast), and hand every other wire message to
client/network_message_adapter.py's NetworkMessageAdapter, which translates
it into a typed domain event and publishes it on self.bus (events/bus.py).
GameViewState itself never mutates status-banner state - StatusBannerState
below is a Bus subscriber, same as SoundCues/GameAnimationCues, and owns
that reaction entirely on its own. Before this split, apply_message
dispatched wire messages through a private message_type -> bound-method
table and had disconnect_countdown/ack write straight into this object's
own fields - a hand-rolled, string-keyed Subject/Observer that only this
class could ever add a listener to, and that mixed wire-parsing with view
state in one place.
"""

import time
from dataclasses import dataclass
from typing import Optional

from client.network_message_adapter import DisconnectCountdownEvent, MoveRejectedEvent, NetworkMessageAdapter
from events.bus import Bus
from events.game_animations import GameAnimationCues
from events.game_events import GameStartedEvent
from events.sound import SoundCues
from model.game_state import GameSnapshot
from server.protocol import PanelState, snapshot_from_json


# Published only by GameViewState.apply_message's own snapshot branch below,
# and only ever subscribed to by StatusBannerState - unlike
# DisconnectCountdownEvent/MoveRejectedEvent (client/network_message_adapter.py),
# there's no wire message type carrying this; it exists purely so
# StatusBannerState's end-of-batch "did a snapshot arrive without a
# countdown" check (see its own end_batch) can react to the snapshot the
# same way it reacts to every other event, through the Bus, instead of
# GameViewState reaching into it directly.
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
# and a rejected move combine into one line of text. Not "...Cues" like
# those two: it holds standing state across ticks rather than firing a
# one-shot reaction (a sound, a triggered animation) per event.
class StatusBannerState:
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
        self.status_banner = StatusBannerState(self.bus)
        self.message_adapter = NetworkMessageAdapter(self.bus)
        self.bus.publish(GameStartedEvent())

    def begin_batch(self) -> None:
        self.status_banner.begin_batch()

    def apply_message(self, message: dict) -> None:
        if "pieces" in message:
            self.snapshot = snapshot_from_json(message)
            self.panel_state.update_from_json(message)
            self.bus.publish(SnapshotAppliedEvent())
            return

        self.message_adapter.apply(message)

    def end_batch(self) -> None:
        self.status_banner.end_batch()

    @property
    def status_message(self) -> Optional[str]:
        return self.status_banner.status_message
