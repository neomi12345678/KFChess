from config import CELL_SIZE, JUMP_TIME_MS
from piece import is_empty
from state import AirbornePiece, GameState


def handle_jump(state: GameState, x: int, y: int) -> None:
    if state.game_over:
        return

    if x < 0 or y < 0:
        return

    rows = len(state.board)
    cols = len(state.board[0]) if rows else 0
    r = y // CELL_SIZE
    c = x // CELL_SIZE

    if r < 0 or r >= rows or c < 0 or c >= cols:
        return

    piece = state.board[r][c]
    if is_empty(piece):
        return

    cell_is_moving = any(mp.sr == r and mp.sc == c for mp in state.moving_pieces)
    if cell_is_moving:
        return

    if any(ap.r == r and ap.c == c for ap in state.airborne_pieces):
        return

    state.airborne_pieces.append(AirbornePiece(piece=piece, r=r, c=c, remaining=JUMP_TIME_MS))
    if state.selected == (r, c):
        state.selected = None
