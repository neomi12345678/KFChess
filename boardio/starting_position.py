"""The one real starting position both the local GUI (app_builder.py's
build_app) and the networked server (server/main.py's _new_board) parse a
fresh Board from - kept here, not copy-pasted in both, so a rule change to
the standard setup (or a variant board) only ever needs editing once.
"""

STARTING_BOARD = """
bR bN bB bQ bK bB bN bR
bP bP bP bP bP bP bP bP
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
wP wP wP wP wP wP wP wP
wR wN wB wQ wK wB wN wR
""".strip()
