from dataclasses import dataclass
from typing import List, Optional

from config import CELL_SIZE
from model.board import BoardRepresentation
from model.piece import AIRBORNE, MOVING
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine
from rules.win_condition import KingCaptureWinCondition, WinCondition


@dataclass
class MoveResult:
    is_accepted: bool
    reason: str


@dataclass
class JumpResult:
    is_accepted: bool
    reason: str


@dataclass
class PieceSnapshot:
    id: str
    kind: str
    color: str
    pixel_x: int
    pixel_y: int
    state: str


@dataclass
class GameSnapshot:
    board_width: int
    board_height: int
    pieces: List[PieceSnapshot]
    selected_cell: Optional[Position]
    game_over: bool


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

        piece = self._board.get_piece(source)
        if piece is not None and piece.state == MOVING:
            return MoveResult(is_accepted=False, reason="motion_in_progress")

        if piece is not None and piece.state == AIRBORNE:
            return MoveResult(is_accepted=False, reason="piece_is_airborne")

        if self._real_time_arbiter.has_route_conflict(source, destination):
            return MoveResult(is_accepted=False, reason="route_conflict")

        validation = self._rule_engine.validate_move(self._board, source, destination)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        self._real_time_arbiter.start_motion(piece, source, destination)

        return MoveResult(is_accepted=True, reason="ok")

    def request_jump(self, position: Position) -> JumpResult:
        if self.game_over:
            return JumpResult(is_accepted=False, reason="game_over")

        piece = self._board.get_piece(position)
        if piece is None:
            return JumpResult(is_accepted=False, reason="empty_cell")

        if not self._real_time_arbiter.start_jump(piece):
            return JumpResult(is_accepted=False, reason="piece_is_moving")

        return JumpResult(is_accepted=True, reason="ok")

    def wait(self, ms: int) -> None:
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


def _interpolated_pixels(motion) -> tuple:
    progress = min(1.0, motion.elapsed_ms / motion.duration_ms) if motion.duration_ms else 1.0
    row = motion.source.row + (motion.destination.row - motion.source.row) * progress
    col = motion.source.col + (motion.destination.col - motion.source.col) * progress
    return int(col * CELL_SIZE + CELL_SIZE // 2), int(row * CELL_SIZE + CELL_SIZE // 2)
