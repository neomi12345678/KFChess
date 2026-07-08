from config import CELL_SIZE, MOVE_TIME_PER_CELL
from piece import color, is_empty
from rules.movement_rules import can_move
from state import GameState, MovingPiece


def handle_click(state: GameState, x: int, y: int) -> None:
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

    cell = state.board[r][c]
    cell_is_moving = any(mp.sr == r and mp.sc == c for mp in state.moving_pieces) or any(
        ap.r == r and ap.c == c for ap in state.airborne_pieces
    )

    if state.selected is None:
        if not is_empty(cell) and not cell_is_moving:
            state.selected = (r, c)
        return

    sr, sc = state.selected
    piece = state.board[sr][sc]

    if (not is_empty(cell) and color(cell) == color(piece) and not cell_is_moving):
        state.selected = (r, c)
        return

    if can_move(state.board, piece, sr, sc, r, c, rows):
        state.moving_pieces.append(
            MovingPiece(piece=piece, sr=sr, sc=sc, r=r, c=c, remaining=MOVE_TIME_PER_CELL)
        )
    state.selected = None
