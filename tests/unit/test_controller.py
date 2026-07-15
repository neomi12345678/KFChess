from engine.game_engine import GameEngine
from input.board_mapper import BoardMapper
from input.controller import Controller
from boardio.board_parser import parse
from model.piece import is_selectable
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


class FakeGameEngine:
    """Stands in for GameEngine's query surface only (can_select/
    is_same_color/request_move/request_jump) - a real object, not a mock,
    reading the same Board a real GameEngine would hold internally (see
    engine/game_engine.py's own can_select/is_same_color)."""

    def __init__(self, board):
        self._board = board
        self.requested_moves = []
        self.requested_jumps = []

    def can_select(self, position):
        piece = self._board.get_piece(position)
        return piece is not None and is_selectable(piece.state)

    def is_same_color(self, position_a, position_b):
        piece_a = self._board.get_piece(position_a)
        piece_b = self._board.get_piece(position_b)
        return piece_a is not None and piece_b is not None and piece_a.color == piece_b.color

    def request_move(self, source, destination):
        self.requested_moves.append((source, destination))

    def request_jump(self, position):
        self.requested_jumps.append(position)


def make_controller(board_text):
    board = parse(board_text)
    mapper = BoardMapper(width=board.width, height=board.height)
    engine = FakeGameEngine(board)
    controller = Controller(board_mapper=mapper, game_engine=engine)
    return controller, engine


def test_first_click_on_a_piece_sets_selected_cell():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    result = controller.click(50, 50)

    assert controller.selected == Position(0, 0)
    assert result.selected == Position(0, 0)
    assert result.move_requested is False
    assert engine.requested_moves == []


def test_first_click_on_an_empty_cell_leaves_selection_empty():
    controller, engine = make_controller(". . .\n. . .\n. . .")

    controller.click(50, 50)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_click_outside_the_board_with_no_selection_does_nothing():
    controller, engine = make_controller(". . .\n. . .\n. . .")

    controller.click(-10, 50)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_click_outside_the_board_with_selection_cancels_it():
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(50, 50)

    controller.click(-10, 50)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_second_in_board_click_sends_move_request_and_clears_selection():
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(50, 50)

    result = controller.click(250, 50)

    assert engine.requested_moves == [(Position(0, 0), Position(0, 2))]
    assert controller.selected is None
    assert result.move_requested is True


def test_selection_clears_after_second_click_even_when_the_engine_rejects_the_move():
    board = parse("wK . .\n. . .\n. . .")
    mapper = BoardMapper(width=board.width, height=board.height)
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))
    controller = Controller(board_mapper=mapper, game_engine=engine)
    controller.click(50, 50)

    result = controller.click(250, 250)

    assert controller.selected is None
    assert result.move_requested is True
    assert board.get_piece(Position(0, 0)) is not None
    assert board.get_piece(Position(2, 2)) is None


def test_clicking_another_own_piece_switches_selection_instead_of_requesting_a_move():
    controller, engine = make_controller("wK . wR\n. . .\n. . .")
    controller.click(50, 50)

    result = controller.click(250, 50)

    assert controller.selected == Position(0, 2)
    assert result.selected == Position(0, 2)
    assert result.move_requested is False
    assert engine.requested_moves == []


def test_clicking_a_friendly_piece_that_is_moving_does_not_switch_selection():
    board = parse("wR . wK\n. . .")
    mapper = BoardMapper(width=board.width, height=board.height)
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))
    controller = Controller(board_mapper=mapper, game_engine=engine)
    controller.click(50, 50)
    controller.click(50, 150)
    controller.click(250, 50)

    result = controller.click(50, 50)

    assert controller.selected == Position(0, 2)
    assert result.selected == Position(0, 2)
    assert result.move_requested is False


def test_clicking_an_enemy_piece_still_requests_a_move():
    controller, engine = make_controller("wK . bR\n. . .\n. . .")
    controller.click(50, 50)

    result = controller.click(250, 50)

    assert engine.requested_moves == [(Position(0, 0), Position(0, 2))]
    assert controller.selected is None
    assert result.move_requested is True


def test_jump_forwards_the_mapped_cell_to_the_game_engine():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    controller.jump(50, 50)

    assert engine.requested_jumps == [Position(0, 0)]


def test_jump_outside_the_board_is_ignored():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    controller.jump(-10, 50)

    assert engine.requested_jumps == []


def test_jump_clears_a_leftover_selection_from_an_earlier_click():
    # A click before a jump (selecting a piece, then jumping a different
    # one instead of completing the move) must not leave stale selection
    # state around to hijack the next click as a move request.
    controller, engine = make_controller("wK . bR\n. . .\n. . .")
    controller.click(50, 50)  # selects the king
    assert controller.selected == Position(0, 0)

    controller.jump(250, 50)  # jumps the rook instead

    assert controller.selected is None

    controller.click(150, 50)  # should select this cell, not request a move
    assert engine.requested_moves == []
