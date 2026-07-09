from model.board import Board
from model.position import Position

EMPTY_TOKEN = "."


def print_board(board: Board) -> str:
    lines = []
    for r in range(board.height):
        cells = []
        for c in range(board.width):
            piece = board.get_piece(Position(r, c))
            cells.append(EMPTY_TOKEN if piece is None else f"{piece.color}{piece.kind}")
        lines.append(" ".join(cells))
    return "\n".join(lines)
