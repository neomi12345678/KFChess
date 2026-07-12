from typing import Iterable, Protocol, Set, Tuple

from model.board import BoardRepresentation
from model.piece import Piece, WHITE
from model.position import Position


class PieceRule(Protocol):
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        ...


_ROOK_DIRECTIONS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
_BISHOP_DIRECTIONS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
_QUEEN_DIRECTIONS = _ROOK_DIRECTIONS + _BISHOP_DIRECTIONS
_KNIGHT_OFFSETS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
_KING_OFFSETS = _QUEEN_DIRECTIONS


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
        return _slide(board, piece, _ROOK_DIRECTIONS)


class BishopRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _slide(board, piece, _BISHOP_DIRECTIONS)


class QueenRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _slide(board, piece, _QUEEN_DIRECTIONS)


class KnightRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _single_step(board, piece, _KNIGHT_OFFSETS)


class KingRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        return _single_step(board, piece, _KING_OFFSETS)


class PawnRule:
    def legal_destinations(self, board: BoardRepresentation, piece: Piece) -> Set[Position]:
        destinations = set()
        forward = -1 if piece.color == WHITE else 1
        start_row = board.height - 1 if piece.color == WHITE else 0
        row = piece.cell.row + forward

        forward_position = Position(row, piece.cell.col)
        forward_open = board.is_in_bounds(forward_position) and board.get_piece(forward_position) is None
        if forward_open:
            destinations.add(forward_position)

            if piece.cell.row == start_row:
                double_position = Position(row + forward, piece.cell.col)
                if board.is_in_bounds(double_position) and board.get_piece(double_position) is None:
                    destinations.add(double_position)

        for dc in (-1, 1):
            capture_position = Position(row, piece.cell.col + dc)
            if not board.is_in_bounds(capture_position):
                continue

            occupant = board.get_piece(capture_position)
            if occupant is not None and occupant.color != piece.color:
                destinations.add(capture_position)

        return destinations
