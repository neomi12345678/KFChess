"""Wraps a single in-progress game for the networked server: which color
each connection controls, and the one authorization check GameEngine itself
never makes (see engine/game_engine.py - request_move/request_jump take no
color argument at all, since this is a real-time game with no turn order to
enforce it through). Everything else - move legality, cooldowns, route
conflicts - is still entirely GameEngine's call; this only ever gates
"is this connection allowed to move *this* piece at all" before asking it.

A GameSession is created only once matchmaking (server/matchmaking.py) has
already paired two authenticated usernames - unlike stages 2-4, a seat is no
longer claimed by connection order, so this class takes both usernames up
front instead of exposing an assign_seat()/login() step of its own.
"""

import math
from typing import Dict, List, Optional, Union

from app import build_game
from events.bus import Bus
from events.bus_bridge import BusBridge
from events.game_events import GameStartedEvent
from events.observers import MoveLogObserver, ScoreObserver
from model.board import BoardRepresentation
from model.game_state import ArrivalEvent, GameObserver, JumpResult, MoveLoggedEvent, MoveResult
from model.piece import ActionResultReason, BLACK, KING, WHITE
from model.position import Position
from server.accounts import AccountStore
from server.protocol import JUMP, Command
from server.rating import updated_ratings

# Shared with server/ws_server.py (see its own import of this constant) -
# "the other seat" is the same lookup whether it's this module deciding a
# resignation's winner or ws_server.py addressing the disconnect-countdown
# broadcast at the opponent.
OTHER_SEAT = {WHITE: BLACK, BLACK: WHITE}

# How long a disconnected seat gets before it's ruled a resignation (see
# resign()) - the Home-screen slide's own "auto-resign after 20 sec".
DISCONNECT_GRACE_MS = 20_000


# Subscribes to the bus's ArrivalEvent stream (see GameSession.__init__ and
# model/game_state.py's GameObserver, the same on_arrival hook
# events/observers.py's MoveLogObserver/ScoreObserver use) purely to learn
# *which color's king* was captured - GameEngine.game_over is already True
# by the time the same wait() call returns, but it never says who lost,
# only that the game ended.
class _KingCaptureWatcher(GameObserver):
    def __init__(self):
        self.loser_color: Optional[str] = None

    def on_arrival(self, event: ArrivalEvent) -> None:
        if event.captured_piece is not None and event.captured_piece.kind == KING:
            self.loser_color = event.captured_piece.color


class GameSession:
    # disconnect_grace_ms is injectable so tests can use a grace window
    # measured in milliseconds instead of actually waiting out the real
    # 20-second default (see server/ws_server.py's own disconnect_grace_ms).
    def __init__(
        self,
        board: BoardRepresentation,
        account_store: AccountStore,
        white_username: str,
        black_username: str,
        disconnect_grace_ms: int = DISCONNECT_GRACE_MS,
    ):
        self._board = board
        self.game_engine, _controller, _board_mapper = build_game(board)
        self._account_store = account_store
        self._usernames: Dict[str, str] = {WHITE: white_username, BLACK: black_username}

        # Same Bus/BusBridge wiring game_builder.py's build_app uses for the
        # local GUI's sound/animation cues - the king-capture watcher, move
        # log, and score are subscribers here too, not GameEngine observers
        # in their own right. GameEngine itself only ever sees BusBridge
        # (see events/bus_bridge.py); server/ws_server.py has no notion of
        # this bus itself, only of the move_log/score it accumulates (see
        # server/protocol.py's panel_to_json) and the wire events it buffers
        # for a networked client's own sound cues (see drain_wire_events).
        self._bus = Bus()
        self._king_capture_watcher = _KingCaptureWatcher()
        self._bus.subscribe(ArrivalEvent, self._king_capture_watcher.on_arrival)
        self.move_log = MoveLogObserver(board_height=board.height)
        self.score = ScoreObserver()
        self._bus.subscribe(MoveLoggedEvent, self.move_log.on_move_logged)
        self._bus.subscribe(ArrivalEvent, self.move_log.on_arrival)
        self._bus.subscribe(ArrivalEvent, self.score.on_arrival)

        # The bare minimum a networked client needs to fire the same
        # move/jump/capture sound cue a local GameEngine-fed Bus would (see
        # events/sound.py's SoundCues) - buffered here rather than sent
        # immediately, since GameSession has no notion of websockets or
        # broadcasting (see this module's own docstring); server/ws_server.py
        # drains this once per tick (see drain_wire_events) and broadcasts
        # each entry as its own message, instead of a networked client
        # re-guessing "was that a capture?" from the move-log's own notation
        # text the way it used to.
        self._pending_wire_events: List[dict] = []
        self._bus.subscribe(MoveLoggedEvent, self._buffer_move_logged)
        self._bus.subscribe(ArrivalEvent, self._buffer_capture)

        self.game_engine.add_observer(BusBridge(self._bus))
        self._bus.publish(GameStartedEvent())

        self._ratings_finalized = False
        self._disconnect_grace_ms = disconnect_grace_ms
        # Only present while a seat's connection is currently disconnected -
        # absent means "connected" (see mark_disconnected/mark_reconnected).
        self._disconnected_ms: Dict[str, int] = {}

    def _buffer_move_logged(self, event: MoveLoggedEvent) -> None:
        self._pending_wire_events.append({"type": "move_logged", "is_jump": event.is_jump})

    # Fires on every arrival, but only ever buffered for a capture - a
    # networked client's SoundCues only reacts to ArrivalEvent.captured_piece
    # being non-None (see events/sound.py's SoundCues._on_arrival), so a
    # quiet arrival has nothing worth telling it about. Buffered as soon as
    # this fires, same as a local Bus would - including a mid-flight
    # interception's capture (has_landed=False), which the old notation-
    # guessing approach could only ever detect once the mover's own move-log
    # entry was finally corrected at landing (see events/observers.py's
    # MoveLogObserver.on_arrival).
    def _buffer_capture(self, event: ArrivalEvent) -> None:
        if event.captured_piece is not None:
            self._pending_wire_events.append({"type": "capture"})

    # Drains every wire event buffered since the last call, in order - see
    # server/ws_server.py's _advance_game, the only caller, once per tick.
    def drain_wire_events(self) -> List[dict]:
        events = self._pending_wire_events
        self._pending_wire_events = []
        return events

    @property
    def board_height(self) -> int:
        return self._board.height

    def username_for(self, seat: str) -> str:
        return self._usernames[seat]

    def seat_for_username(self, username: str) -> Optional[str]:
        for seat, name in self._usernames.items():
            if name == username:
                return seat
        return None

    def mark_disconnected(self, seat: str) -> None:
        self._disconnected_ms[seat] = 0

    def mark_reconnected(self, seat: str) -> None:
        self._disconnected_ms.pop(seat, None)

    def is_disconnected(self, seat: str) -> bool:
        return seat in self._disconnected_ms

    # How many whole seconds remain before a still-disconnected seat is
    # ruled a resignation - the "count down" the Home-screen slide asks to
    # show the opponent (see server/ws_server.py's disconnect_countdown
    # broadcast). None once the seat isn't disconnected at all.
    def seconds_remaining_for(self, seat: str) -> Optional[int]:
        if seat not in self._disconnected_ms:
            return None
        return math.ceil(max(0, self._disconnect_grace_ms - self._disconnected_ms[seat]) / 1000)

    # Ages every currently-disconnected seat's grace timer by elapsed_ms.
    # Returns the seat that just crossed the grace window unresolved, or
    # None if nobody did - doesn't itself force the resignation (see
    # resign()), just reports the fact so the caller can decide what to do
    # with it (and keep broadcasting the countdown in the meantime).
    def advance_disconnect_grace(self, elapsed_ms: int) -> Optional[str]:
        expired_seat = None
        for seat in list(self._disconnected_ms):
            self._disconnected_ms[seat] += elapsed_ms
            if self._disconnected_ms[seat] >= self._disconnect_grace_ms:
                expired_seat = seat
        return expired_seat

    # Forces the game to end with `seat` as the loser - a disconnect
    # timeout, not a king capture. Reuses the same loser_color field
    # finalize_ratings_if_game_over already reads, and GameEngine's own
    # public game_over flag (the same one it sets itself on an ordinary
    # win - see engine/game_engine.py's wait()) - a resignation is still
    # exactly "the game is over, and here's who lost", the only two facts
    # that matter downstream.
    def resign(self, seat: str) -> None:
        self._king_capture_watcher.loser_color = seat
        self.game_engine.game_over = True

    # Once per completed game: if GameEngine.game_over just became true
    # (a king capture or a resignation - see resign()), computes and
    # persists the ELO update for both accounts and returns the new
    # ratings keyed by seat color; returns None on every other tick (game
    # still in progress, or already finalized once).
    def finalize_ratings_if_game_over(self) -> Optional[Dict[str, int]]:
        if self._ratings_finalized or not self.game_engine.game_over:
            return None

        loser_seat = self._king_capture_watcher.loser_color
        if loser_seat is None:
            return None

        winner_seat = OTHER_SEAT[loser_seat]
        winner_username = self._usernames[winner_seat]
        loser_username = self._usernames[loser_seat]

        self._ratings_finalized = True

        winner_rating = self._account_store.rating_for(winner_username)
        loser_rating = self._account_store.rating_for(loser_username)
        new_winner_rating, new_loser_rating = updated_ratings(winner_rating, loser_rating)

        self._account_store.update_rating(winner_username, new_winner_rating)
        self._account_store.update_rating(loser_username, new_loser_rating)

        return {winner_seat: new_winner_rating, loser_seat: new_loser_rating}

    def apply_command(self, command: Command) -> Union[MoveResult, JumpResult]:
        piece = self._board.get_piece(command.source)
        if piece is None or piece.color != command.color:
            reason = ActionResultReason.NOT_YOUR_PIECE
            if command.kind == JUMP:
                return JumpResult(is_accepted=False, reason=reason)
            return MoveResult(is_accepted=False, reason=reason)

        if command.kind == JUMP:
            return self.game_engine.request_jump(command.source)
        return self.game_engine.request_move(command.source, command.destination)

    def tick(self, elapsed_ms: int) -> None:
        self.game_engine.wait(elapsed_ms)

    def snapshot(self, selected: Optional[Position] = None):
        return self.game_engine.snapshot(selected=selected)
