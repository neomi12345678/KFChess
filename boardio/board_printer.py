from boardio.board_parser import piece_to_token
from logic_config import EMPTY_TOKEN
from model.board import BoardRepresentation
from model.position import Position


# Pure formatting: returns text instead of printing it, so callers decide
# whether to display it, assert on it, or write it to a stream.
#
# Deliberately reads BoardRepresentation's resting grid, not
# engine.game_engine.GameEngine.snapshot() the way view/renderer.py does -
# GameSnapshot.pieces reports each piece's *interpolated* float row/col
# mid-motion (see GameEngine.snapshot's docstring), which has no honest
# single-cell answer to round to. A .kfc script's `print board` command
# wants a deterministic snapshot of where pieces actually rest, the same
# thing board_parser.parse reads back in - not a mid-flight approximation.
# This is a second read path by design, not a drift risk: it's the same
# Board instance GameEngine itself holds (see texttests/script_runner.py),
# just read directly instead of through GameEngine's own query surface,
# because GameEngine exposes no board-shaped accessor to route through.
def print_board(board: BoardRepresentation) -> str:
    lines = []
    for r in range(board.height):
        cells = []
        for c in range(board.width):
            piece = board.get_piece(Position(r, c))
            cells.append(EMPTY_TOKEN if piece is None else piece_to_token(piece))
        lines.append(" ".join(cells))
    return "\n".join(lines)
