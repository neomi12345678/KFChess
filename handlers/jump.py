from config import JUMP_TIME_MS
from coords import pixel_to_cell
from piece import is_empty
from state import AirbornePiece, GameState


def handle_jump(state: GameState, x: int, y: int) -> None:
    if state.game_over:
        return

    cell_coords = pixel_to_cell(state.board, x, y)
    if cell_coords is None:
        return
    r, c = cell_coords

    piece = state.board[r][c]
    if is_empty(piece):
        return

    if state.is_cell_in_flight(r, c):
        return

    state.airborne_pieces.append(AirbornePiece(piece=piece, r=r, c=c, remaining=JUMP_TIME_MS))
    if state.selected == (r, c):
        state.selected = None
