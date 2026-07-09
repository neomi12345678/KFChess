from dataclasses import dataclass

from model.board import Board
from model.position import Position
from rules.piece_rules import BishopRule, KingRule, KnightRule, PawnRule, QueenRule, RookRule

_PIECE_RULES = {
    "R": RookRule(),
    "B": BishopRule(),
    "Q": QueenRule(),
    "N": KnightRule(),
    "K": KingRule(),
    "P": PawnRule(),
}


@dataclass
class MoveValidation:
    is_valid: bool
    reason: str


class RuleEngine:
    def validate_move(self, board: Board, source: Position, destination: Position) -> MoveValidation:
        if not board.is_in_bounds(source) or not board.is_in_bounds(destination):
            return MoveValidation(is_valid=False, reason="outside_board")

        piece = board.get_piece(source)
        if piece is None:
            return MoveValidation(is_valid=False, reason="empty_source")

        target = board.get_piece(destination)
        if target is not None and target.color == piece.color:
            return MoveValidation(is_valid=False, reason="friendly_destination")

        rule = _PIECE_RULES.get(piece.kind)
        if rule is None or destination not in rule.legal_destinations(board, piece):
            return MoveValidation(is_valid=False, reason="illegal_piece_move")

        return MoveValidation(is_valid=True, reason="ok")
