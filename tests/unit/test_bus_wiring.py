"""Proves the whole events/bus.py wiring works together against a real
GameEngine - the same shape game_builder.py's build_app() wires up (BusBridge as
the one GameObserver, everything else a bus subscriber), not just each
piece in isolation.
"""

from boardio.board_parser import parse
from engine.game_engine import GameEngine
from events.bus import Bus
from events.bus_bridge import BusBridge
from events.game_animations import GAME_END_ANIMATION, GAME_START_ANIMATION, GameAnimationCues
from events.game_events import GameStartedEvent
from events.observers import MoveLogObserver, ScoreObserver
from events.sound import CAPTURE_CUE, GAME_END_CUE, GAME_START_CUE, MOVE_CUE, SoundCues
from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import WHITE
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


def test_a_real_king_capture_reaches_every_bus_subscriber():
    # A 1x2 board: white rook right next to black's king - one move
    # captures it and ends the game.
    board = parse("wR bK")
    game_engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))

    move_log = MoveLogObserver(board_height=board.height)
    score = ScoreObserver()
    bus = Bus()
    bus.subscribe(MoveLoggedEvent, move_log.on_move_logged)
    bus.subscribe(ArrivalEvent, move_log.on_arrival)
    bus.subscribe(ArrivalEvent, score.on_arrival)
    sound = SoundCues(bus)
    animations = GameAnimationCues(bus)
    game_engine.add_observer(BusBridge(bus))

    bus.publish(GameStartedEvent())
    assert sound.played == [GAME_START_CUE]
    assert animations.triggered == [GAME_START_ANIMATION]

    result = game_engine.request_move(Position(0, 0), Position(0, 1))
    assert result.is_accepted is True

    game_engine.wait(667 + 1)  # 1 cell at MOVE_CELL_DURATION_MS=667, plus margin

    assert game_engine.game_over is True
    assert [entry.notation for entry in move_log.entries_for(WHITE)] == ["Rxb1"]
    assert score.score_for(WHITE) == 0  # capturing a king scores nothing (see PIECE_VALUES)
    assert sound.played == [GAME_START_CUE, MOVE_CUE, CAPTURE_CUE, GAME_END_CUE]
    assert animations.triggered == [GAME_START_ANIMATION, GAME_END_ANIMATION]
