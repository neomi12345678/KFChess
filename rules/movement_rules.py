from piece import color, kind, is_empty
from config import BISHOP_KIND, KING_KIND, KNIGHT_KIND, PAWN_KIND, QUEEN_KIND, ROOK_KIND, WHITE_COLOR

REQUIRES_PATH = {ROOK_KIND, BISHOP_KIND, QUEEN_KIND}


def clear_path(board, sr, sc, r, c):
    step_r = 0
    step_c = 0

    if r > sr:
        step_r = 1
    elif r < sr:
        step_r = -1

    if c > sc:
        step_c = 1
    elif c < sc:
        step_c = -1

    x = sr + step_r
    y = sc + step_c

    while x != r or y != c:
        if not is_empty(board[x][y]):
            return False

        x += step_r
        y += step_c

    return True


def king_rule(board, piece, sr, sc, r, c, rows):
    dr = abs(r - sr)
    dc = abs(c - sc)
    return dr <= 1 and dc <= 1


def rook_rule(board, piece, sr, sc, r, c, rows):
    return sr == r or sc == c


def bishop_rule(board, piece, sr, sc, r, c, rows):
    return abs(r - sr) == abs(c - sc)


def queen_rule(board, piece, sr, sc, r, c, rows):
    return rook_rule(board, piece, sr, sc, r, c, rows) or bishop_rule(board, piece, sr, sc, r, c, rows)


def knight_rule(board, piece, sr, sc, r, c, rows):
    dr = abs(r - sr)
    dc = abs(c - sc)
    return (dr == 2 and dc == 1) or (dr == 1 and dc == 2)


def pawn_rule(board, piece, sr, sc, r, c, rows):
    dr = r - sr
    dc = abs(c - sc)
    piece_color = color(piece)
    forward = -1 if piece_color == WHITE_COLOR else 1
    start_row = rows - 1 if piece_color == WHITE_COLOR else 0

    if dr == forward and dc == 0 and is_empty(board[r][c]):
        return True
    if sr == start_row and dr == 2 * forward and dc == 0:
        mid = sr + forward
        return is_empty(board[mid][sc]) and is_empty(board[r][c])
    if dr == forward and dc == 1 and not is_empty(board[r][c]) and color(board[r][c]) != piece_color:
        return True
    return False


MOVEMENT_RULES = {
    KING_KIND: king_rule,
    QUEEN_KIND: queen_rule,
    ROOK_KIND: rook_rule,
    BISHOP_KIND: bishop_rule,
    KNIGHT_KIND: knight_rule,
    PAWN_KIND: pawn_rule,
}


def can_move(board, piece, sr, sc, r, c, rows):
    if is_empty(piece):
        return False

    target = board[r][c]
    if not is_empty(target) and color(target) == color(piece):
        return False

    rule = MOVEMENT_RULES.get(kind(piece))
    if rule is None:
        return False

    if not rule(board, piece, sr, sc, r, c, rows):
        return False

    if kind(piece) in REQUIRES_PATH:
        return clear_path(board, sr, sc, r, c)

    return True


