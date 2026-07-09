from dataclasses import dataclass
from typing import List, Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import CAPTURED, IDLE, MOVING, Piece
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import Motion


@dataclass
class ArrivalEvent:
    piece: Piece
    captured_piece: Optional[Piece]


class RealTimeArbiter:
    def __init__(self, board: Board):
        self._board = board
        self._active_motion: Optional[Motion] = None

    def has_active_motion(self) -> bool:
        return self._active_motion is not None

    def get_active_motion(self) -> Optional[Motion]:
        return self._active_motion

    def start_motion(self, piece: Piece, source: Position, destination: Position) -> None:
        self._active_motion = Motion(piece=piece, source=source, destination=destination)
        piece.state = MOVING

    def advance_time(self, ms: int) -> List[ArrivalEvent]:
        if self._active_motion is None:
            return []

        self._active_motion.elapsed_ms += ms

        if not self._active_motion.is_complete():
            return []

        motion = self._active_motion
        self._active_motion = None
        return [self._resolve_arrival(motion)]

    def _resolve_arrival(self, motion: Motion) -> ArrivalEvent:
        captured_piece = self._board.get_piece(motion.destination)
        self._board.remove_piece(motion.source)

        if captured_piece is not None:
            self._board.remove_piece(motion.destination)
            captured_piece.state = CAPTURED

        self._board.add_piece(motion.destination, motion.piece)
        motion.piece.state = IDLE

        return ArrivalEvent(piece=motion.piece, captured_piece=captured_piece)
