# Test suite: https://github.com/neomi12345678/KFChess

import sys
from dataclasses import dataclass

from board import parse_board, validate_board
from config import CELL_SIZE, MOVE_TIME_PER_CELL
from piece import EMPTY, color, is_empty
from pieces import can_move, on_arrival


@dataclass
class MovingPiece:
    piece: str
    sr: int
    sc: int
    r: int
    c: int
    remaining: int


lines = [line.strip() for line in sys.stdin.read().splitlines()]


if "Board:" not in lines:
    sys.exit()


board = parse_board(lines)

validate_board(board)


rows = len(board)
cols = len(board[0]) if rows else 0


selected = None
moving_piece = None
game_over = False


if "Commands:" in lines:

    i = lines.index("Commands:") + 1

    while i < len(lines):

        cmd = lines[i].split()

        if not cmd:
            i += 1
            continue


        if cmd[0] == "click":
            if game_over:
                i += 1
                continue

            if moving_piece is not None:
                i += 1
                continue

            x = int(cmd[1])
            y = int(cmd[2])


            if x < 0 or y < 0:
                i += 1
                continue


            c = x // CELL_SIZE
            r = y // CELL_SIZE


            if r < 0 or r >= rows or c < 0 or c >= cols:
                i += 1
                continue


            cell = board[r][c]

            if selected is None:
                if not is_empty(cell):
                    selected = (r, c)
            else:
                sr, sc = selected
                piece = board[sr][sc]

                if not is_empty(cell) and color(cell) == color(piece):
                    selected = (r, c)
                else:
                    if can_move(board, piece, sr, sc, r, c, rows):
                        distance = max(abs(r - sr), abs(c - sc))
                        moving_piece = MovingPiece(piece, sr, sc, r, c, distance * MOVE_TIME_PER_CELL)
                        selected = None



        elif cmd[0] == "print" and len(cmd) > 1 and cmd[1] == "board":

            for row in board:
                print(" ".join(row))


        elif cmd[0] == "wait":
            t = int(cmd[1])

            if moving_piece is not None:
                piece = moving_piece.piece
                sr = moving_piece.sr
                sc = moving_piece.sc
                r = moving_piece.r
                c = moving_piece.c
                remaining = moving_piece.remaining

                remaining -= t
                if remaining <= 0:
                    target = board[r][c]

                    # אם יש כלי של אותו צד ביעד - אי אפשר לנחות עליו
                    if not is_empty(target) and color(target) == color(piece):
                        moving_piece = None
                        selected = None
                    else:
                        captured = board[r][c]
                        board[r][c] = on_arrival(piece, r, rows)
                        board[sr][sc] = EMPTY
                        moving_piece = None

                        # אכלנו מלך - המשחק נגמר
                        if captured == "wK" or captured == "bK":
                            game_over = True
                else:
                    moving_piece = MovingPiece(piece, sr, sc, r, c, remaining)

        i += 1