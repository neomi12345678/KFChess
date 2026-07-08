from piece_codec import format_piece
from state import GameState


def handle_print_board(state: GameState, output) -> None:
    for row in state.board:
        output.write(" ".join(format_piece(cell) for cell in row) + "\n")
