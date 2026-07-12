from typing import Protocol

from model.piece import PAWN, Piece, QUEEN, WHITE


class PromotionRule(Protocol):
    """Decides whether/how a piece transforms after arriving somewhere.

    Swappable so a custom variant (e.g. a pawn that reverses direction at
    the last rank instead of promoting) can define its own behavior
    without touching RealTimeArbiter.
    """

    def promote(self, piece: Piece, board_height: int) -> None:
        ...


class LastRankPromotion:
    def __init__(self, promotable_kind: str = PAWN, promote_to: str = QUEEN):
        self._promotable_kind = promotable_kind
        self._promote_to = promote_to

    def promote(self, piece: Piece, board_height: int) -> None:
        if piece.kind != self._promotable_kind:
            return

        last_rank = 0 if piece.color == WHITE else board_height - 1
        if piece.cell.row == last_rank:
            piece.kind = self._promote_to
