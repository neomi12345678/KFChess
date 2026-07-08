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
        if board[x][y] != ".":
            return False

        x += step_r
        y += step_c

    return True


def can_move(board, piece, sr, sc, r, c, rows):    
    dr = abs(r - sr)
    dc = abs(c - sc)

    can_move = False


    if piece[1] == 'K':
        can_move = dr <= 1 and dc <= 1

    elif piece[1] == 'Q':
        can_move = (sr == r or sc == c) or (dr == dc)

    elif piece[1] == 'R':
        can_move = (sr == r or sc == c)

    elif piece[1] == 'B':
        can_move = (dr == dc)

    elif piece[1] == 'N':
        can_move = (dr == 2 and dc == 1) or (dr == 1 and dc == 2)

    elif piece[1] == 'P':

        if piece[0] == 'w':

            if r == sr - 1 and c == sc and board[r][c] == ".":
                can_move = True

            elif sr == rows-1 and r == sr - 2 and c == sc:
                if board[sr-1][sc] == "." and board[r][c] == ".":
                    can_move = True

            elif r == sr - 1 and abs(c-sc) == 1:
                if board[r][c] != "." and board[r][c][0] == 'b':
                    can_move = True


        else:

            if r == sr + 1 and c == sc and board[r][c] == ".":
                can_move = True

            elif sr == 0 and r == sr + 2 and c == sc:
                if board[sr+1][sc] == "." and board[r][c] == ".":
                    can_move = True

            elif r == sr + 1 and abs(c-sc) == 1:
                if board[r][c] != "." and board[r][c][0] == 'w':
                    can_move = True
                    
    if can_move and piece[1] in ['R', 'B', 'Q']:
        can_move = clear_path(board, sr, sc, r, c)

    return can_move