from dataclasses import dataclass
from typing import List, Optional, Tuple

from board import BoardValidationError, parse_board, validate_board
from commands import ClickCommand, Command, JumpCommand, PrintBoardCommand, WaitCommand, parse_commands
from config import BOARD_MARKER, CELL_SIZE, COMMANDS_MARKER, JUMP_TIME_MS, MOVE_TIME_PER_CELL
from rules.movement_rules import can_move
from rules.arrival_rules import on_arrival
from rules.game_rules import is_winning_capture
from piece import EMPTY, color, is_empty
from piece_codec import format_piece


@dataclass
class MovingPiece:
    piece: str
    sr: int
    sc: int
    r: int
    c: int
    remaining: int


@dataclass
class AirbornePiece:
    piece: str
    r: int
    c: int
    remaining: int


@dataclass
class GameState:
    board: List[List[str]]
    selected: Optional[Tuple[int, int]] = None
    moving_pieces: List[MovingPiece] = None
    airborne_pieces: List[AirbornePiece] = None
    game_over: bool = False

    def __post_init__(self):
        if self.moving_pieces is None:
            self.moving_pieces = []
        if self.airborne_pieces is None:
            self.airborne_pieces = []


def run(lines: List[str], output=None):
    if output is None:
        from sys import stdout

        output = stdout

    if BOARD_MARKER not in lines:
        return None

    try:
        board = parse_board(lines)
        validate_board(board)
    except BoardValidationError as error:
        output.write(f"ERROR {error.code}\n")
        return None

    state = GameState(board=board)

    if COMMANDS_MARKER not in lines:
        # No commands section at all: this is the "pure parse/validate/print"
        # case (the original, pre-command iteration). There is no explicit
        # `print board` to wait for, so we print the canonical board once and
        # we're done. This branch must NOT run when a Commands: section is
        # present but simply lacks a `print board` line - that case stays
        # silent, exactly as before, to avoid changing behavior any later
        # iteration already depends on.
        handle_print_board(state, output)
        return state.board

    commands = parse_commands(lines)

    for command in commands:
        if isinstance(command, ClickCommand):
            if not state.game_over:
                handle_click(state, command.x, command.y)
        elif isinstance(command, JumpCommand):
            if not state.game_over:
                handle_jump(state, command.x, command.y)
        elif isinstance(command, WaitCommand):
            handle_wait(state, command.ms)
        elif isinstance(command, PrintBoardCommand):
            handle_print_board(state, output)

    return state.board


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


def handle_print_board(state: GameState, output) -> None:
    for row in state.board:
        output.write(" ".join(format_piece(cell) for cell in row) + "\n")