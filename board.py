from config import BOARD_MARKER, COMMANDS_MARKER
from piece import EMPTY, all_piece_names
from piece_codec import parse_piece_token


class BoardValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_board(board):
    legal = {EMPTY} | all_piece_names()

    if board:
        width = len(board[0])

        for row in board:
            if len(row) != width:
                    raise BoardValidationError("ROW_WIDTH_MISMATCH")

            for cell in row:
                if cell not in legal:
                    raise BoardValidationError("UNKNOWN_TOKEN")
def parse_board(lines):
    i = lines.index(BOARD_MARKER) + 1

    board = []

    while i < len(lines) and lines[i] != COMMANDS_MARKER:
        if lines[i]:
            board.append([parse_piece_token(tok) for tok in lines[i].split()])
        i += 1

    return board