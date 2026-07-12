from dataclasses import dataclass
from typing import Dict, Optional, Protocol

from model.board import BoardRepresentation
from model.piece import BISHOP, KING, KNIGHT, PAWN, Piece, QUEEN, ROOK, WHITE
from model.position import Position
from rules.piece_rules import BishopRule, KingRule, KnightRule, PawnRule, PieceRule, QueenRule, RookRule

# The default chess piece set. A custom game passes its own dict to
# RuleEngine instead of editing this one.
STANDARD_PIECE_RULES: Dict[str, PieceRule] = {
    ROOK: RookRule(),
    BISHOP: BishopRule(),
    QUEEN: QueenRule(),
    KNIGHT: KnightRule(),
    KING: KingRule(),
    PAWN: PawnRule(),
}


@dataclass
class MoveValidation:
    is_valid: bool
    reason: str


class RuleEngine:
    # Injectable rule set: pass a custom dict to support non-standard
    # piece kinds without changing this class at all.
    def __init__(self, piece_rules: Optional[Dict[str, PieceRule]] = None):
        self._piece_rules = piece_rules if piece_rules is not None else STANDARD_PIECE_RULES

    def validate_move(self, board: BoardRepresentation, source: Position, destination: Position) -> MoveValidation:
        if not board.is_in_bounds(source) or not board.is_in_bounds(destination):
            return MoveValidation(is_valid=False, reason="outside_board")

        piece = board.get_piece(source)
        if piece is None:
            return MoveValidation(is_valid=False, reason="empty_source")

        target = board.get_piece(destination)
        if target is not None and target.color == piece.color:
            return MoveValidation(is_valid=False, reason="friendly_destination")

        # Delegate the actual shape/blocking check to the piece's own rule.
        rule = self._piece_rules.get(piece.kind)
        if rule is None or destination not in rule.legal_destinations(board, piece):
            return MoveValidation(is_valid=False, reason="illegal_piece_move")

        return MoveValidation(is_valid=True, reason="ok")


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

        # Mirrors PawnRule's own start-row logic: "last rank" is whichever
        # edge this color is advancing toward.
        last_rank = 0 if piece.color == WHITE else board_height - 1
        if piece.cell.row == last_rank:
            piece.kind = self._promote_to
