"""Builds a headless GameEngine from a parsed board - the one place every
caller (server/session.py, main.py's text-script runner, app_builder.py's
build_app) gets this wiring from, so a constructor change to
GameEngine/RuleEngine/RealTimeArbiter only needs updating here.

Deliberately knows nothing about pixels or input handling: no board_offset_x,
no cell_size, no Controller/BoardMapper. A GUI-facing caller layers that on
top separately via input/controller_builder.py's build_controller; a
headless caller (server/session.py) never needs to call that at all, so it
never even imports display_config's pixel constants by way of this module.
"""

from engine.game_engine import GameEngine
from model.board import BoardRepresentation
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


def build_game(board: BoardRepresentation) -> GameEngine:
    real_time_arbiter = RealTimeArbiter(board)
    return GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=real_time_arbiter)
