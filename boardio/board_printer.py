from boardio.board_parser import piece_to_token
from logic_config import EMPTY_TOKEN
from model.board import BoardRepresentation
from model.position import Position


# Pure formatting: returns text instead of printing it, so callers decide
# whether to display it, assert on it, or write it to a stream.
def print_board(board: BoardRepresentation) -> str:
    lines = []
    for r in range(board.height):
        cells = []
        for c in range(board.width):
            piece = board.get_piece(Position(r, c))
            cells.append(EMPTY_TOKEN if piece is None else piece_to_token(piece))
        lines.append(" ".join(cells))
    return "\n".join(lines)
