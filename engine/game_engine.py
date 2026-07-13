from typing import Optional

from config import CELL_SIZE
from model.board import BoardRepresentation
from model.game_state import GameSnapshot, JumpResult, MoveResult, PieceSnapshot
from model.piece import AIRBORNE, MOVING
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

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        if self.game_over:
            return MoveResult(is_accepted=False, reason="game_over")

        # A piece already committed to a motion or jump can't be
        # redirected until that action finishes.
        piece = self._board.get_piece(source)
        if piece is not None and piece.state == MOVING:
            return MoveResult(is_accepted=False, reason="motion_in_progress")

        if piece is not None and piece.state == AIRBORNE:
            return MoveResult(is_accepted=False, reason="piece_is_airborne")

        if piece is not None and self._real_time_arbiter.is_in_cooldown(piece):
            return MoveResult(is_accepted=False, reason="piece_in_cooldown")

        validation = self._rule_engine.validate_move(self._board, source, destination)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        # start_motion may shorten or refuse this move if it collides with
        # an in-flight motion - piece.state is already IDLE here.
        if not self._real_time_arbiter.start_motion(piece, source, destination):
            return MoveResult(is_accepted=False, reason="route_conflict")

        return MoveResult(is_accepted=True, reason="ok")

    def request_jump(self, position: Position) -> JumpResult:
        if self.game_over:
            return JumpResult(is_accepted=False, reason="game_over")

        piece = self._board.get_piece(position)
        if piece is None:
            return JumpResult(is_accepted=False, reason="empty_cell")

        if self._real_time_arbiter.is_in_cooldown(piece):
            return JumpResult(is_accepted=False, reason="piece_in_cooldown")

        if not self._real_time_arbiter.start_jump(piece):
            return JumpResult(is_accepted=False, reason="piece_is_moving")

        return JumpResult(is_accepted=True, reason="ok")

    def wait(self, ms: int) -> None:
        # advance_time may resolve several arrivals in one call (concurrent
        # motions can complete on the same tick) - check every one of them.
        events = self._real_time_arbiter.advance_time(ms)
        for event in events:
            if self._win_condition.is_game_over(event.captured_piece):
                self.game_over = True

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
                pixel_x, pixel_y = _cell_center(row, col)
                motion = motion_by_piece_id.get(piece.id)
                if motion is not None:
                    pixel_x, pixel_y = _interpolated_pixels(motion)

                pieces.append(
                    PieceSnapshot(
                        id=piece.id,
                        kind=piece.kind,
                        color=piece.color,
                        pixel_x=pixel_x,
                        pixel_y=pixel_y,
                        state=piece.state,
                    )
                )

        return GameSnapshot(
            board_width=self._board.width,
            board_height=self._board.height,
            pieces=pieces,
            selected_cell=selected,
            game_over=self.game_over,
        )


def _cell_center(row: int, col: int) -> tuple:
    return col * CELL_SIZE + CELL_SIZE // 2, row * CELL_SIZE + CELL_SIZE // 2


# Linear interpolation between source and destination based on how much of
# the motion's total duration has elapsed.
def _interpolated_pixels(motion) -> tuple:
    progress = min(1.0, motion.elapsed_ms / motion.duration_ms) if motion.duration_ms else 1.0
    row = motion.source.row + (motion.destination.row - motion.source.row) * progress
    col = motion.source.col + (motion.destination.col - motion.source.col) * progress
    return int(col * CELL_SIZE + CELL_SIZE // 2), int(row * CELL_SIZE + CELL_SIZE // 2)
