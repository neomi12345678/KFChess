from dataclasses import dataclass
from typing import List, Optional

from model.board import Board
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine

CELL_SIZE = 100


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
    def __init__(self, board: Board, rule_engine: RuleEngine, real_time_arbiter: RealTimeArbiter):
        self._board = board
        self._rule_engine = rule_engine
        self._real_time_arbiter = real_time_arbiter
        self.game_over = False

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        if self.game_over:
            return MoveResult(is_accepted=False, reason="game_over")

        if self._real_time_arbiter.has_active_motion():
            return MoveResult(is_accepted=False, reason="motion_in_progress")

        validation = self._rule_engine.validate_move(self._board, source, destination)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        piece = self._board.get_piece(source)
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
            if event.captured_piece is not None and event.captured_piece.kind == "K":
                self.game_over = True

    def snapshot(self, selected: Optional[Position] = None) -> GameSnapshot:
        active_motion = self._real_time_arbiter.get_active_motion()
        pieces = []

        for row in range(self._board.height):
            for col in range(self._board.width):
                piece = self._board.get_piece(Position(row, col))
                if piece is None:
                    continue

                pixel_x, pixel_y = _cell_center(row, col)
                if active_motion is not None and active_motion.piece is piece:
                    pixel_x, pixel_y = _interpolated_pixels(active_motion)

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
