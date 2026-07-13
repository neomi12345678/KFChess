from typing import Iterable, Protocol, Set, Tuple

from config import BISHOP_DIRECTIONS, KING_OFFSETS, KNIGHT_OFFSETS, QUEEN_DIRECTIONS, ROOK_DIRECTIONS
from model.board import BoardRepresentation
from model.piece import Piece, WHITE
from model.position import Position


# Extension point: any object with this method can be registered as a
# piece's movement rule, including custom/non-standard piece kinds.
class PieceRule(Protocol):
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        ...


# Shared by rook/bishop/queen: walk outward from the piece in each
# direction, stopping at the board edge, a friendly piece (excluded), or
# an enemy piece (included as a capture, then stop).
def _slide(board: BoardRepresentation, piece: Piece, directions: Iterable[Tuple[int, int]]) -> Set[Position]:
    destinations = set()

    for dr, dc in directions:
        r, c = piece.cell.row + dr, piece.cell.col + dc

        while board.is_in_bounds(Position(r, c)):
            position = Position(r, c)
            occupant = board.get_piece(position)

            if occupant is None:
                destinations.add(position)
            elif occupant.color != piece.color:
                destinations.add(position)
                break
            else:
                break

            r += dr
            c += dc

    return destinations


# Shared by knight/king: a fixed set of destination offsets, no path
# blocking in between (a knight jumps over anything).
def _single_step(board: BoardRepresentation, piece: Piece, offsets: Iterable[Tuple[int, int]]) -> Set[Position]:
    destinations = set()

    for dr, dc in offsets:
        position = Position(piece.cell.row + dr, piece.cell.col + dc)
        if not board.is_in_bounds(position):
            continue

        occupant = board.get_piece(position)
        if occupant is None or occupant.color != piece.color:
            destinations.add(position)

    return destinations


class RookRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _slide(board, piece, ROOK_DIRECTIONS)


class BishopRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _slide(board, piece, BISHOP_DIRECTIONS)


class QueenRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _slide(board, piece, QUEEN_DIRECTIONS)


class KnightRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _single_step(board, piece, KNIGHT_OFFSETS)


class KingRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _single_step(board, piece, KING_OFFSETS)


class PawnRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        destinations = set()
        # White advances toward row 0, black toward the last row.
        forward = -1 if piece.color == WHITE else 1
        # Pawns start one row in from their own back edge - the edge row
        # itself is the back rank (king, rooks, ...), not a pawn square.
        start_row = board.height - 2 if piece.color == WHITE else 1
        row = piece.cell.row + forward

        forward_position = Position(row, piece.cell.col)
        forward_open = board.is_in_bounds(forward_position) and board.get_piece(forward_position) is None
        if forward_open:
            destinations.add(forward_position)

            # Double-step only from the start row, and only if both the
            # intermediate and destination squares are empty.
            if piece.cell.row == start_row:
                double_position = Position(row + forward, piece.cell.col)
                if board.is_in_bounds(double_position) and board.get_piece(double_position) is None:
                    destinations.add(double_position)

        # Diagonal squares are only reachable as a capture - never as a
        # plain move, even if empty.
        for dc in (-1, 1):
            capture_position = Position(row, piece.cell.col + dc)
            if not board.is_in_bounds(capture_position):
                continue

            occupant = board.get_piece(capture_position)
            if occupant is not None and occupant.color != piece.color:
                destinations.add(capture_position)

        return destinations
