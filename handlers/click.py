from config import MOVE_TIME_PER_CELL
from piece import color, is_empty
from rules.movement_rules import can_move
from state import GameState, MovingPiece, pixel_to_cell


def handle_click(state: GameState, x: int, y: int) -> None:
    if state.game_over:
        return

    cell_coords = pixel_to_cell(state.board, x, y)
    if cell_coords is None:
        return
    r, c = cell_coords

    cell = state.board[r][c]
    cell_is_moving = state.is_cell_in_flight(r, c)

    if state.selected is None:
        if not is_empty(cell) and not cell_is_moving:
            state.selected = (r, c)
        return

    sr, sc = state.selected
    piece = state.board[sr][sc]

    if (not is_empty(cell) and color(cell) == color(piece) and not cell_is_moving):
        state.selected = (r, c)
        return

    if can_move(state.board, piece, sr, sc, r, c, len(state.board)):
        state.moving_pieces.append(
            MovingPiece(piece=piece, sr=sr, sc=sc, r=r, c=c, remaining=MOVE_TIME_PER_CELL)
        )
    state.selected = None
