from engine.game_engine import GameEngine
from input.controller import Controller
from boardio.board_parser import parse
from model.piece import Piece, ROOK, WHITE, is_selectable
from model.position import Position
from realtime.real_time_arbiter import RealTimeArbiter
from rules.rule_engine import RuleEngine


class FakeGameEngine:
    """Stands in for GameEngine's query surface only (can_select/
    is_same_color/piece_id_at/request_move/request_jump) - a real object,
    not a mock, reading the same Board a real GameEngine would hold
    internally (see engine/game_engine.py's own can_select/is_same_color/
    piece_id_at)."""

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

    def piece_id_at(self, position):
        piece = self._board.get_piece(position)
        return piece.id if piece is not None else None

    def request_move(self, source, destination):
        self.requested_moves.append((source, destination))

    def request_jump(self, position):
        self.requested_jumps.append(position)


def make_controller(board_text):
    board = parse(board_text)
    engine = FakeGameEngine(board)
    controller = Controller(game_engine=engine)
    return controller, engine


def test_first_click_on_a_piece_sets_selected_cell():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    result = controller.click(Position(0, 0))

    assert controller.selected == Position(0, 0)
    assert result.selected == Position(0, 0)
    assert result.move_requested is False
    assert engine.requested_moves == []


def test_first_click_on_an_empty_cell_leaves_selection_empty():
    controller, engine = make_controller(". . .\n. . .\n. . .")

    controller.click(Position(0, 0))

    assert controller.selected is None
    assert engine.requested_moves == []


def test_click_with_no_resolved_cell_and_no_selection_does_nothing():
    # cell is None whenever the caller's own pixel->cell translation (see
    # input/board_mapper.py) missed the board entirely - Controller itself
    # never knows or cares why.
    controller, engine = make_controller(". . .\n. . .\n. . .")

    controller.click(None)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_click_with_no_resolved_cell_cancels_an_existing_selection():
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(Position(0, 0))

    controller.click(None)

    assert controller.selected is None
    assert engine.requested_moves == []


def test_second_in_board_click_sends_move_request_and_clears_selection():
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(Position(0, 0))

    result = controller.click(Position(0, 2))

    assert engine.requested_moves == [(Position(0, 0), Position(0, 2))]
    assert controller.selected is None
    assert result.move_requested is True


def test_selection_clears_after_second_click_even_when_the_engine_rejects_the_move():
    board = parse("wK . .\n. . .\n. . .")
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))
    controller = Controller(game_engine=engine)
    controller.click(Position(0, 0))

    result = controller.click(Position(2, 2))

    assert controller.selected is None
    assert result.move_requested is True
    assert board.get_piece(Position(0, 0)) is not None
    assert board.get_piece(Position(2, 2)) is None


def test_clicking_another_own_piece_switches_selection_instead_of_requesting_a_move():
    controller, engine = make_controller("wK . wR\n. . .\n. . .")
    controller.click(Position(0, 0))

    result = controller.click(Position(0, 2))

    assert controller.selected == Position(0, 2)
    assert result.selected == Position(0, 2)
    assert result.move_requested is False
    assert engine.requested_moves == []


def test_clicking_a_friendly_piece_that_is_moving_does_not_switch_selection():
    board = parse("wR . wK\n. . .")
    engine = GameEngine(board=board, rule_engine=RuleEngine(), real_time_arbiter=RealTimeArbiter(board))
    controller = Controller(game_engine=engine)
    controller.click(Position(0, 0))
    controller.click(Position(1, 0))
    controller.click(Position(0, 2))

    result = controller.click(Position(0, 0))

    assert controller.selected == Position(0, 2)
    assert result.selected == Position(0, 2)
    assert result.move_requested is False


def test_clicking_an_enemy_piece_still_requests_a_move():
    controller, engine = make_controller("wK . bR\n. . .\n. . .")
    controller.click(Position(0, 0))

    result = controller.click(Position(0, 2))

    assert engine.requested_moves == [(Position(0, 0), Position(0, 2))]
    assert controller.selected is None
    assert result.move_requested is True


def test_second_click_is_ignored_when_a_different_piece_now_occupies_the_selected_cell():
    # Real wall-clock time passes between two clicks in interactive play -
    # the originally selected piece may have been captured, with an
    # unrelated piece's motion since landing on that same cell, before the
    # second click arrives. Position alone can't tell the two pieces apart;
    # only identity can (see Controller._selected_piece_id).
    controller, engine = make_controller("wK . .\n. . .\n. . .")
    controller.click(Position(0, 0))
    assert controller.selected == Position(0, 0)

    engine._board.remove_piece(Position(0, 0))
    engine._board.add_piece(Position(0, 0), Piece(id="impostor", color=WHITE, kind=ROOK, cell=Position(0, 0)))

    result = controller.click(Position(0, 2))

    assert controller.selected is None
    assert result.move_requested is False
    assert engine.requested_moves == []


def test_jump_forwards_the_cell_to_the_game_engine():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    controller.jump(Position(0, 0))

    assert engine.requested_jumps == [Position(0, 0)]


def test_jump_with_no_resolved_cell_is_ignored():
    controller, engine = make_controller("wK . .\n. . .\n. . .")

    controller.jump(None)

    assert engine.requested_jumps == []


def test_jump_clears_a_leftover_selection_from_an_earlier_click():
    # A click before a jump (selecting a piece, then jumping a different
    # one instead of completing the move) must not leave stale selection
    # state around to hijack the next click as a move request.
    controller, engine = make_controller("wK . bR\n. . .\n. . .")
    controller.click(Position(0, 0))  # selects the king
    assert controller.selected == Position(0, 0)

    controller.jump(Position(0, 2))  # jumps the rook instead

    assert controller.selected is None

    controller.click(Position(0, 1))  # should select this cell, not request a move
    assert engine.requested_moves == []
