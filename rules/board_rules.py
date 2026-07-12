from dataclasses import dataclass

from model.board import BoardRepresentation
from model.position import Position


@dataclass
class BoardCheck:
    is_valid: bool
    reason: str


class BoardRules:
    """Board-level move legality: bounds and occupancy, independent of any
    piece's movement shape. Kept separate from RuleEngine's piece-shape
    check (rules/piece_rules.py) so the two concerns can be read, tested,
    and swapped independently.
    """

    def check(self, board: BoardRepresentation, source: Position, destination: Position) -> BoardCheck:
        if not board.is_in_bounds(source) or not board.is_in_bounds(destination):
            return BoardCheck(is_valid=False, reason="outside_board")

        piece = board.get_piece(source)
        if piece is None:
            return BoardCheck(is_valid=False, reason="empty_source")

        target = board.get_piece(destination)
        if target is not None and target.color == piece.color:
            return BoardCheck(is_valid=False, reason="friendly_destination")

        return BoardCheck(is_valid=True, reason="ok")
