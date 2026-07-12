from dataclasses import dataclass
from typing import Dict, Optional

from model.board import Board
from model.piece import BISHOP, KING, KNIGHT, PAWN, QUEEN, ROOK
from model.position import Position
from rules.piece_rules import BishopRule, KingRule, KnightRule, PawnRule, PieceRule, QueenRule, RookRule

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
    def __init__(self, piece_rules: Optional[Dict[str, PieceRule]] = None):
        self._piece_rules = piece_rules if piece_rules is not None else STANDARD_PIECE_RULES

    def validate_move(self, board: Board, source: Position, destination: Position) -> MoveValidation:
        if not board.is_in_bounds(source) or not board.is_in_bounds(destination):
            return MoveValidation(is_valid=False, reason="outside_board")

        piece = board.get_piece(source)
        if piece is None:
            return MoveValidation(is_valid=False, reason="empty_source")

        target = board.get_piece(destination)
        if target is not None and target.color == piece.color:
            return MoveValidation(is_valid=False, reason="friendly_destination")

        rule = self._piece_rules.get(piece.kind)
        if rule is None or destination not in rule.legal_destinations(board, piece):
            return MoveValidation(is_valid=False, reason="illegal_piece_move")

        return MoveValidation(is_valid=True, reason="ok")
