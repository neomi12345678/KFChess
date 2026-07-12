from typing import Optional, Protocol

from model.piece import KING, Piece


class WinCondition(Protocol):
    """Decides whether a capture ends the game.

    Swappable so a custom variant (capture-the-flag, last-piece-standing,
    ...) can define its own ending condition without touching GameEngine.
    """

    def is_game_over(self, captured_piece: Optional[Piece]) -> bool:
        ...


class KingCaptureWinCondition:
    def is_game_over(self, captured_piece: Optional[Piece]) -> bool:
        return captured_piece is not None and captured_piece.kind == KING
