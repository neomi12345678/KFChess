import sys
from board import parse_board, validate_board
from pieces import can_move


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


            c = x // 100
            r = y // 100


            if r < 0 or r >= rows or c < 0 or c >= cols:
                i += 1
                continue


            cell = board[r][c]


            if selected is None:

                if cell != ".":
                    selected = (r, c)


            else:

                sr, sc = selected
                piece = board[sr][sc]


                if cell != "." and cell[0] == piece[0]:
                    selected = (r, c)


                else:

                    if can_move(board, piece, sr, sc, r, c, rows):
                        distance = max(abs(r - sr), abs(c - sc))
                        moving_piece = (piece, sr, sc, r, c, distance * 1000)
                        selected = None



        elif cmd[0] == "print" and len(cmd) > 1 and cmd[1] == "board":

            for row in board:
                print(" ".join(row))


        elif cmd[0] == "wait":
            t = int(cmd[1])

            if moving_piece is not None:
                piece, sr, sc, r, c, remaining = moving_piece

                remaining -= t
                if remaining <= 0:

                    target = board[r][c]

                    # אם יש כלי של אותו צד ביעד - אי אפשר לנחות עליו
                    if target != "." and target[0] == piece[0]:
                        moving_piece = None
                        selected = None

                    else:
                        # שומרים מה היה במשבצת לפני האכילה
                        captured = board[r][c]
                    
                        board[r][c] = piece
                        board[sr][sc] = "."
                        if piece == "wP" and r == 0:
                            board[r][c] = "wQ"

                        elif piece == "bP" and r == rows-1:
                            board[r][c] = "bQ"
                        
                        moving_piece = None
                    
                        # אכלנו מלך - המשחק נגמר
                        if captured == "wK" or captured == "bK":
                            game_over = True
                else:
                    moving_piece = (piece, sr, sc, r, c, remaining)
                                    

        i += 1