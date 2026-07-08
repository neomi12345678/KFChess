from typing import List

from piece import EMPTY, color, is_empty
from rules.arrival_rules import on_arrival
from rules.game_rules import is_winning_capture
from state import AirbornePiece, GameState, MovingPiece


def handle_wait(state: GameState, ms: int) -> None:
    next_moving_pieces: List[MovingPiece] = []
    for mp in state.moving_pieces:
        remaining = mp.remaining - ms
        if remaining <= 0:
            resolve_arrival(state, mp)
        else:
            next_moving_pieces.append(MovingPiece(mp.piece, mp.sr, mp.sc, mp.r, mp.c, remaining))

    next_airborne_pieces: List[AirbornePiece] = []
    for ap in state.airborne_pieces:
        remaining = ap.remaining - ms
        if remaining > 0:
            next_airborne_pieces.append(AirbornePiece(ap.piece, ap.r, ap.c, remaining))

    state.moving_pieces = next_moving_pieces
    state.airborne_pieces = next_airborne_pieces


def resolve_arrival(state: GameState, moving_piece: MovingPiece) -> None:
    airborne_here = next(
        (
            ap for ap in state.airborne_pieces
            if ap.r == moving_piece.r and ap.c == moving_piece.c
            and color(ap.piece) != color(moving_piece.piece)
        ),
        None,
    )
    if airborne_here is not None:
        state.board[moving_piece.sr][moving_piece.sc] = EMPTY
        state.airborne_pieces = [ap for ap in state.airborne_pieces if ap is not airborne_here]
        if is_winning_capture(moving_piece.piece):
            state.game_over = True
        return

    target = state.board[moving_piece.r][moving_piece.c]
    if not is_empty(target) and color(target) == color(moving_piece.piece):
        state.selected = None
        return

    captured = state.board[moving_piece.r][moving_piece.c]
    state.board[moving_piece.r][moving_piece.c] = on_arrival(moving_piece.piece, moving_piece.r, len(state.board))
    state.board[moving_piece.sr][moving_piece.sc] = EMPTY

    if is_winning_capture(captured):
        state.game_over = True
