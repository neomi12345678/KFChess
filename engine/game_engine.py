from typing import List, Optional

from model.board import BoardRepresentation
from model.game_state import GameObserver, GameSnapshot, JumpResult, MoveLoggedEvent, MoveResult, PieceSnapshot
from model.piece import PHASE_IDLE, PHASE_JUMP, PHASE_MOVE, MOVING, is_selectable, jump_availability, move_availability
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import KingCaptureWinCondition, RuleEngine, WinCondition


class GameEngine:
    def __init__(
        self,
        board: BoardRepresentation,
        rule_engine: RuleEngine,
        real_time_arbiter: RealTimeArbiter,
        win_condition: Optional[WinCondition] = None,
    ):
        self._board = board
        self._rule_engine = rule_engine
        self._real_time_arbiter = real_time_arbiter
        self._win_condition = win_condition if win_condition is not None else KingCaptureWinCondition()
        self.game_over = False
        self._observers: List[GameObserver] = []
        # Drives moves-log timestamps off the same simulated clock wait()
        # already advances everything else by, instead of time.monotonic() -
        # keeps it tied to realtime/'s own notion of "now" and trivially
        # testable without sleeping.
        self._elapsed_ms = 0

    # GameEngine never needs to know a moves log or scoreboard exist - it
    # just notifies whoever is registered (view/observers.py) and moves on,
    # so the move/jump pipeline never waits on them.
    def add_observer(self, observer: GameObserver) -> None:
        self._observers.append(observer)

    # The single gate for "may this cell be selected right now?" - Controller
    # (input/controller.py) calls this instead of reading Board/RealTimeArbiter
    # itself, so selection permission has exactly one source of truth, shared
    # with request_move/request_jump's own state checks below. Doesn't check
    # game_over on its own: a selection query is harmless once the game has
    # ended, and request_move/request_jump already gate on it before doing
    # anything that matters.
    def can_select(self, position: Position) -> bool:
        piece = self._board.get_piece(position)
        if piece is None:
            return False
        if not is_selectable(piece.state):
            return False
        if self._real_time_arbiter.is_airborne(piece):
            return False
        if self._real_time_arbiter.is_in_cooldown(piece):
            return False
        return True

    # Whether the two cells hold pieces of the same color - Controller uses
    # this to decide "switch selection" vs. "request a move/capture" without
    # ever reading a Piece itself.
    def is_same_color(self, position_a: Position, position_b: Position) -> bool:
        piece_a = self._board.get_piece(position_a)
        piece_b = self._board.get_piece(position_b)
        return piece_a is not None and piece_b is not None and piece_a.color == piece_b.color

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        if self.game_over:
            return MoveResult(is_accepted=False, reason="game_over")

        # A piece already committed to a motion, still resting, or currently
        # airborne, can't be redirected. Airborne/resting are never part of
        # piece.state itself (see model/piece.py) - only RealTimeArbiter's
        # own out-of-band bookkeeping (is_airborne()/is_in_cooldown()) knows
        # which, so those are checked here directly instead of through
        # move_availability's table.
        piece = self._board.get_piece(source)
        if piece is not None:
            if self._real_time_arbiter.is_airborne(piece):
                return MoveResult(is_accepted=False, reason="piece_is_airborne")

            availability = move_availability(piece.state)
            if not availability.allowed:
                return MoveResult(is_accepted=False, reason=availability.reason_if_blocked)

            if self._real_time_arbiter.is_in_cooldown(piece):
                return MoveResult(is_accepted=False, reason="piece_in_cooldown")

        validation = self._rule_engine.validate_move(self._board, source, destination)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        # Peeked before start_motion, which never mutates the board itself
        # (only realtime/real_time_arbiter.py's _resolve_arrival does, once
        # this motion later arrives) - is_capture is reported as-is to
        # observers (see MoveLoggedEvent), so a route conflict that later
        # truncates the destination can leave it a display-only
        # approximation of what actually happened. GameEngine doesn't
        # correct for that itself - see model/game_state.py's
        # MoveLoggedEvent docstring for why that's the view layer's problem,
        # not this one's.
        is_capture = self._board.get_piece(destination) is not None

        # start_motion may shorten or refuse this move if it collides with
        # an in-flight motion - piece.state is already IDLE here.
        if not self._real_time_arbiter.start_motion(piece, source, destination):
            return MoveResult(is_accepted=False, reason="route_conflict")

        self._notify_move(
            color=piece.color,
            kind=piece.kind,
            source=source,
            destination=destination,
            is_capture=is_capture,
            is_jump=False,
        )

        return MoveResult(is_accepted=True, reason="ok")

    def request_jump(self, position: Position) -> JumpResult:
        if self.game_over:
            return JumpResult(is_accepted=False, reason="game_over")

        piece = self._board.get_piece(position)
        if piece is None:
            return JumpResult(is_accepted=False, reason="empty_cell")

        if self._real_time_arbiter.is_airborne(piece):
            return JumpResult(is_accepted=False, reason="piece_is_moving")

        availability = jump_availability(piece.state)
        if not availability.allowed:
            return JumpResult(is_accepted=False, reason=availability.reason_if_blocked)

        if self._real_time_arbiter.is_in_cooldown(piece):
            return JumpResult(is_accepted=False, reason="piece_in_cooldown")

        # Unlike start_motion (which can still refuse over a route
        # conflict even once availability passes), start_jump's only
        # rejection condition is the same state check availability already
        # covered above - so, unlike request_move, there's no second,
        # independent reason its result needs checking for here.
        self._real_time_arbiter.start_jump(piece)

        # A jump has no destination (see RealTimeArbiter.start_jump) - the
        # piece's own current cell stands in for both source and
        # destination in the event this produces.
        self._notify_move(
            color=piece.color,
            kind=piece.kind,
            source=position,
            destination=position,
            is_capture=False,
            is_jump=True,
        )

        return JumpResult(is_accepted=True, reason="ok")

    def wait(self, ms: int) -> None:
        self._elapsed_ms += ms

        # advance_time may resolve several arrivals in one call (concurrent
        # motions can complete on the same tick) - check every one of them.
        events = self._real_time_arbiter.advance_time(ms)
        for event in events:
            for observer in self._observers:
                observer.on_arrival(event)
            if self._win_condition.is_game_over(event.captured_piece):
                self.game_over = True

    def _notify_move(
        self, *, color: str, kind: str, source: Position, destination: Position, is_capture: bool, is_jump: bool
    ) -> None:
        event = MoveLoggedEvent(
            color=color,
            kind=kind,
            source=source,
            destination=destination,
            is_capture=is_capture,
            is_jump=is_jump,
            elapsed_ms=self._elapsed_ms,
        )
        for observer in self._observers:
            observer.on_move_logged(event)

    def snapshot(self, selected: Optional[Position] = None) -> GameSnapshot:
        motion_by_piece_id = {
            motion.piece.id: motion for motion in self._real_time_arbiter.get_active_motions()
        }
        pieces = []

        for row in range(self._board.height):
            for col in range(self._board.width):
                piece = self._board.get_piece(Position(row, col))
                if piece is None:
                    continue

                # Pieces mid-flight are still stored at their source cell
                # on the board, so their on-screen position has to be
                # interpolated rather than read straight off the grid.
                board_row, board_col = float(row), float(col)
                motion = motion_by_piece_id.get(piece.id)
                if motion is not None:
                    board_row, board_col = _interpolated_cell(motion)

                pieces.append(
                    PieceSnapshot(
                        id=piece.id,
                        kind=piece.kind,
                        color=piece.color,
                        row=board_row,
                        col=board_col,
                        state=piece.state,
                        motion_phase=self._motion_phase(piece),
                    )
                )

        return GameSnapshot(
            board_width=self._board.width,
            board_height=self._board.height,
            pieces=tuple(pieces),
            selected_cell=selected,
            game_over=self.game_over,
        )

    # Only ever PHASE_IDLE/MOVE/JUMP - never SHORT_REST/LONG_REST, which are
    # a purely cosmetic overlay view/piece_state_machine.py derives on top
    # of this report (see its own docstring for why the engine itself has no
    # notion that a "rest animation" exists).
    def _motion_phase(self, piece) -> str:
        if self._real_time_arbiter.is_airborne(piece):
            return PHASE_JUMP
        if piece.state == MOVING:
            return PHASE_MOVE
        return PHASE_IDLE


# Linear interpolation between source and destination based on how much of
# the motion's total duration has elapsed.
def _interpolated_cell(motion) -> tuple:
    progress = min(1.0, motion.elapsed_ms / motion.duration_ms) if motion.duration_ms else 1.0
    row = motion.source.row + (motion.destination.row - motion.source.row) * progress
    col = motion.source.col + (motion.destination.col - motion.source.col) * progress
    return row, col
