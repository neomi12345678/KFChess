from piece import is_empty, is_king

"""Game rules extension point.

Future custom win conditions should be implemented by replacing this function
or supplying a different rule to the game logic, not by hard-coding logic in
`game.py`.
"""


def is_winning_capture(captured_piece) -> bool:
    return not is_empty(captured_piece) and is_king(captured_piece)
