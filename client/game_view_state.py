"""State a networked game window (play_online.py) accumulates from the
server's own broadcasts - the latest board/panel snapshot, this client's
local sound/animation Bus, and the two transient status banners
(disconnect countdown, a rejected move) - kept as its own class so the
message-dispatch logic (apply_message) is unit-testable without a real
GameWindow/canvas/renderer, the same way client/network_controller.py's
click/jump logic already is.

There's no GameEngine here to publish MoveLoggedEvent/ArrivalEvent itself
(unlike play.py), so apply_message reconstructs minimal stand-ins for
those two events straight from the server's own "move_logged"/"capture"
wire messages (see server/session.py's drain_wire_events, buffered off the
server's real GameEngine-fed bus) and publishes them on this client's Bus,
same as GameEngine's own BusBridge would - server-authoritative facts, not
a guess reconstructed from move-log notation text. The fields neither
SoundCues nor GameAnimationCues ever reads (piece identity, board
positions, the real captured Piece) are left as placeholders - the wire
never carries them, and nothing downstream looks at them.
"""

import time
from typing import Optional

from events.bus import Bus
from events.game_animations import GameAnimationCues
from events.game_events import GameEndedEvent, GameStartedEvent
from events.sound import SoundCues
from model.game_state import ArrivalEvent, GameSnapshot, MoveLoggedEvent
from server.protocol import PanelState, snapshot_from_json

# How long a rejected move/jump's message stays on screen - the ack itself
# (unlike disconnect_countdown) is a one-off reply, not a standing state
# the server keeps re-broadcasting, so there's no "still true" signal to
# clear it on; it just times out instead.
ILLEGAL_MOVE_MESSAGE_S = 2.0

# A stand-in for the real captured Piece SoundCues/GameAnimationCues never
# actually get here (see this module's own docstring) - ArrivalEvent's
# captured_piece is only ever tested for "is this None or not" by either
# subscriber, never read into, so any non-None object satisfies that check.
_CAPTURED_PIECE_PLACEHOLDER = object()


class GameViewState:
    def __init__(self, first_snapshot_payload: dict):
        self.snapshot: GameSnapshot = snapshot_from_json(first_snapshot_payload)
        self.panel_state = PanelState()
        self.panel_state.update_from_json(first_snapshot_payload)

        # This client's own local Bus - the network counterpart to
        # game_builder.py's build_app wiring the same two subscribers to a
        # GameEngine-fed Bus for local play (see this module's own docstring).
        self.bus = Bus()
        SoundCues(self.bus)
        GameAnimationCues(self.bus)
        self.bus.publish(GameStartedEvent())

        self.disconnect_countdown_text: Optional[str] = None
        self.illegal_move_text: Optional[str] = None
        self._illegal_move_expires_at = 0.0
        self._saw_snapshot_this_batch = False
        self._saw_countdown_this_batch = False

        # message.get("type") -> handler, the one thing apply_message needs
        # per-instance state (self.bus, self._saw_countdown_this_batch, ...)
        # for, so it's built once here instead of as a class-level dict of
        # unbound methods.
        self._message_handlers = {
            "move_logged": self._apply_move_logged,
            "capture": self._apply_capture,
            "game_over": self._apply_game_over,
            "disconnect_countdown": self._apply_disconnect_countdown,
            "ack": self._apply_ack,
        }

    # Called once before draining a poll_messages() batch - see end_batch,
    # which reacts to what apply_message saw (or didn't see) across the
    # whole batch just finished.
    def begin_batch(self) -> None:
        self._saw_snapshot_this_batch = False
        self._saw_countdown_this_batch = False

    def apply_message(self, message: dict) -> None:
        if "pieces" in message:
            self.snapshot = snapshot_from_json(message)
            self.panel_state.update_from_json(message)
            self._saw_snapshot_this_batch = True
            return

        handler = self._message_handlers.get(message.get("type"))
        if handler is not None:
            handler(message)

    def _apply_move_logged(self, message: dict) -> None:
        self.bus.publish(
            MoveLoggedEvent(
                color="",
                kind="",
                source=None,
                destination=None,
                is_capture=False,
                is_jump=message["is_jump"],
                elapsed_ms=0,
                piece_id="",
            )
        )

    def _apply_capture(self, message: dict) -> None:
        self.bus.publish(ArrivalEvent(piece=None, captured_piece=_CAPTURED_PIECE_PLACEHOLDER))

    def _apply_game_over(self, message: dict) -> None:
        print(f"Game over. New ratings: {message['ratings']}")
        # arrival=None - unlike every other GameEndedEvent, there's no
        # ArrivalEvent behind a networked game-over at all (see
        # server/session.py's resign(), a disconnect timeout rather
        # than a king-capture ArrivalEvent), and neither SoundCues nor
        # GameAnimationCues ever reads this field anyway (see this
        # module's own docstring).
        self.bus.publish(GameEndedEvent(arrival=None))

    def _apply_disconnect_countdown(self, message: dict) -> None:
        self.disconnect_countdown_text = (
            f"Opponent disconnected - resigning in {message['seconds_remaining']}s unless they return"
        )
        self._saw_countdown_this_batch = True

    def _apply_ack(self, message: dict) -> None:
        if not message.get("accepted"):
            self.illegal_move_text = f"Illegal move: {message.get('reason')}"
            self._illegal_move_expires_at = time.monotonic() + ILLEGAL_MOVE_MESSAGE_S

    # Called once after a poll_messages() batch has been fully applied -
    # reacts to facts about the whole batch (see the two _saw_*_this_batch
    # flags), not to any single message, so this can't live in
    # apply_message itself.
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
