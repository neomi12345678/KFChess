from piece import color, kind, is_empty, make


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

    if color(piece) == 'w':
        if dr == -1 and dc == 0 and is_empty(board[r][c]):
            return True
        if sr == rows - 2 and dr == -2 and dc == 0:
            return is_empty(board[sr - 1][sc]) and is_empty(board[r][c])
        if dr == -1 and dc == 1 and not is_empty(board[r][c]) and color(board[r][c]) == 'b':
            return True
        return False

    if dr == 1 and dc == 0 and is_empty(board[r][c]):
        return True
    if sr == 1 and dr == 2 and dc == 0:
        return is_empty(board[sr + 1][sc]) and is_empty(board[r][c])
    return dr == 1 and dc == 1 and not is_empty(board[r][c]) and color(board[r][c]) == 'w'


MOVEMENT_RULES = {
    'K': king_rule,
    'Q': queen_rule,
    'R': rook_rule,
    'B': bishop_rule,
    'N': knight_rule,
    'P': pawn_rule,
}


def can_move(board, piece, sr, sc, r, c, rows):
    if is_empty(piece):
        return False

    rule = MOVEMENT_RULES.get(kind(piece))
    if rule is None:
        return False

    if not rule(board, piece, sr, sc, r, c, rows):
        return False

    if kind(piece) in {'R', 'B', 'Q'}:
        return clear_path(board, sr, sc, r, c)

    return True


def on_arrival(piece, r, rows):
    if kind(piece) == 'P' and (r == 0 or r == rows - 1):
        return make(color(piece), 'Q')
    return piece
