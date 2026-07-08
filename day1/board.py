def validate_board(board):
    legal = {
        ".",
        "wK", "wQ", "wR", "wB", "wN", "wP",
        "bK", "bQ", "bR", "bB", "bN", "bP"
    }

    if board:
        width = len(board[0])

        for row in board:
            if len(row) != width:
                print("ERROR ROW_WIDTH_MISMATCH")
                exit()

            for cell in row:
                if cell not in legal:
                    print("ERROR UNKNOWN_TOKEN")
                    exit()


def parse_board(lines):
    i = lines.index("Board:") + 1

    board = []

    while i < len(lines) and lines[i] != "Commands:":
        if lines[i]:
            board.append(lines[i].split())
        i += 1

    return board