from io import StringIO

from config import MOVE_TIME_PER_CELL
from game import run
from handlers.click import handle_click
from handlers.jump import handle_jump
from handlers.print_board import handle_print_board
from handlers.wait import handle_wait, resolve_arrival
from piece import EMPTY
from state import AirbornePiece, GameState, MovingPiece


def make_state(board):
    return GameState(board=board, selected=None, moving_pieces=[], airborne_pieces=[], game_over=False)


def test_run_returns_none_without_board_marker():
    lines = ['Commands:', 'click 50 50']
    assert run(lines) is None


def test_handle_click_negative_coordinates_ignored():
    state = make_state([['wR', '.']])
    handle_click(state, -10, 50)
    assert state.selected is None


def test_handle_click_out_of_bounds_ignored():
    state = make_state([['wR', '.']])
    handle_click(state, 500, 50)
    assert state.selected is None


def test_handle_click_empty_cell_without_selection():
    state = make_state([['.', '.'], ['.', '.']])
    handle_click(state, 50, 50)
    assert state.selected is None


def test_handle_click_ignored_when_game_over():
    state = make_state([['wR', '.']])
    state.game_over = True
    handle_click(state, 50, 50)
    assert state.selected is None


def test_handle_click_illegal_move_resets_selection():
    state = make_state([['wR', '.', '.'], ['.', '.', '.'], ['.', '.', '.']])
    state.selected = (0, 0)
    handle_click(state, 150, 150)
    assert state.selected is None
    assert state.moving_pieces == []


def test_handle_click_move_duration_is_constant_per_move():
    state = make_state([['wR', '.', '.']])
    state.selected = (0, 0)

    handle_click(state, 250, 50)

    assert len(state.moving_pieces) == 1
    assert state.moving_pieces[0].remaining == MOVE_TIME_PER_CELL


def test_resolve_arrival_target_occupied_by_friendly_does_nothing():
    state = make_state([['wR', 'wP'], ['.', '.']])
    mp = MovingPiece(piece='wR', sr=0, sc=0, r=0, c=1, remaining=0)
    state.selected = (0, 0)
    resolve_arrival(state, mp)
    assert state.board == [['wR', 'wP'], ['.', '.']]
    assert state.game_over is False


def test_resolve_arrival_capture_king_sets_game_over():
    state = make_state([['wR', 'bK'], ['.', '.']])
    mp = MovingPiece(piece='wR', sr=0, sc=0, r=0, c=1, remaining=0)
    resolve_arrival(state, mp)
    assert state.game_over
    assert state.board[0][1] == 'wR'


def test_handle_wait_advances_moving_piece_and_arrives():
    state = make_state([['wR', '.'], ['.', '.']])
    state.moving_pieces.append(MovingPiece(piece='wR', sr=0, sc=0, r=0, c=1, remaining=500))
    handle_wait(state, 500)
    assert state.board[0][1] == 'wR'
    assert state.board[0][0] == '.'


def test_handle_jump_sets_airborne_and_leaves_piece_on_board():
    state = make_state([['wN', '.', '.'], ['.', '.', '.'], ['.', '.', '.']])

    handle_jump(state, 50, 50)

    assert state.board[0][0] == 'wN'
    assert len(state.airborne_pieces) == 1
    airborne = state.airborne_pieces[0]
    assert airborne.piece == 'wN'
    assert airborne.r == 0 and airborne.c == 0
    assert airborne.remaining == 1000


def test_handle_jump_ignores_empty_cell():
    state = make_state([['.', '.'], ['.', '.']])

    handle_jump(state, 50, 50)

    assert state.airborne_pieces == []


def test_handle_jump_ignores_moving_piece():
    state = make_state([['wN', '.'], ['.', '.']])
    state.moving_pieces.append(MovingPiece(piece='wN', sr=0, sc=0, r=0, c=1, remaining=500))

    handle_jump(state, 50, 50)

    assert state.airborne_pieces == []


def test_handle_jump_ignores_already_airborne():
    state = make_state([['wN', '.'], ['.', '.']])
    state.airborne_pieces.append(AirbornePiece(piece='wN', r=0, c=0, remaining=500))

    handle_jump(state, 50, 50)

    assert len(state.airborne_pieces) == 1


def test_handle_jump_ignored_when_game_over():
    state = make_state([['wN', '.'], ['.', '.']])
    state.game_over = True

    handle_jump(state, 50, 50)

    assert state.airborne_pieces == []


def test_handle_jump_out_of_bounds_ignored():
    state = make_state([['wN', '.'], ['.', '.']])

    handle_jump(state, 500, 50)

    assert state.airborne_pieces == []


def test_print_board_while_airborne_shows_piece_unchanged():
    state = make_state([['wN', '.'], ['.', '.']])
    handle_jump(state, 50, 50)

    output = StringIO()
    handle_print_board(state, output)

    assert output.getvalue() == 'wN .\n. .\n'


def test_wait_removes_airborne_after_jump_time_and_board_unchanged():
    state = make_state([['wN', '.'], ['.', '.']])
    handle_jump(state, 50, 50)

    handle_wait(state, 1000)

    assert state.airborne_pieces == []
    assert state.board == [['wN', '.'], ['.', '.']]


def test_handle_wait_executes_even_when_game_over():
    state = make_state([['wR', '.', '.']])
    state.game_over = True
    state.moving_pieces.append(MovingPiece(piece='wR', sr=0, sc=0, r=0, c=2, remaining=500))

    handle_wait(state, 500)

    assert state.board[0][2] == 'wR'
    assert state.board[0][0] == '.'


def test_interception_removes_arriving_piece_and_clears_airborne():
    state = make_state([['.', 'bR'], ['.', 'wN']])
    state.airborne_pieces.append(AirbornePiece(piece='wN', r=1, c=1, remaining=1000))
    state.moving_pieces.append(MovingPiece(piece='bR', sr=0, sc=1, r=1, c=1, remaining=500))

    handle_wait(state, 500)

    assert state.board == [['.', '.'], ['.', 'wN']]
    assert state.airborne_pieces == []
    assert state.game_over is False


def test_interception_with_king_sets_game_over():
    state = make_state([['.', 'bK'], ['.', 'wN']])
    state.airborne_pieces.append(AirbornePiece(piece='wN', r=1, c=1, remaining=1000))
    state.moving_pieces.append(MovingPiece(piece='bK', sr=0, sc=1, r=1, c=1, remaining=500))

    handle_wait(state, 500)

    assert state.board == [['.', '.'], ['.', 'wN']]
    assert state.airborne_pieces == []
    assert state.game_over is True


def test_airborne_piece_cannot_be_selected_as_source():
    state = make_state([['wN', '.'], ['.', '.']])
    handle_jump(state, 50, 50)

    handle_click(state, 50, 50)

    assert state.selected is None


def test_airborne_piece_cannot_be_selected_as_destination():
    state = make_state([['wN', 'wR'], ['.', '.']])
    handle_jump(state, 50, 50)
    state.selected = (0, 1)

    handle_click(state, 50, 50)

    assert state.selected is None
    assert state.moving_pieces == []


def test_run_outputs_error_for_invalid_board(tmp_path):
    lines = [
        'Board:',
        'wK bQ',
        'wP',
        'Commands:'
    ]
    output = StringIO()

    assert run(lines, output=output) is None
    assert output.getvalue() == 'ERROR ROW_WIDTH_MISMATCH\n'


def test_run_prints_board_without_commands():
    lines = [
        'Board:',
        'wR . .',
        '. . .',
        '. . .',
    ]
    output = StringIO()

    run(lines, output=output)

    assert output.getvalue() == 'wR . .\n. . .\n. . .\n'


def test_run_errors_without_commands_invalid_board():
    lines = [
        'Board:',
        'wR .',
        '. . .',
    ]
    output = StringIO()

    assert run(lines, output=output) is None
    assert output.getvalue() == 'ERROR ROW_WIDTH_MISMATCH\n'


def test_run_prints_board_with_empty_commands_section():
    lines = [
        'Board:',
        'wR . .',
        '. . .',
        '. . .',
        'Commands:',
    ]
    output = StringIO()

    run(lines, output=output)

    assert output.getvalue() == 'wR . .\n. . .\n. . .\n'


def test_run_does_not_double_print_with_explicit_print_board():
    lines = [
        'Board:',
        'wR . .',
        '. . .',
        '. . .',
        'Commands:',
        'print board',
    ]
    output = StringIO()

    run(lines, output=output)

    assert output.getvalue() == 'wR . .\n. . .\n. . .\n'


def test_run_prints_board_after_game_over():
    lines = [
        'Board:',
        'wR bK .',
        'Commands:',
        'click 50 50',
        'click 150 50',
        'wait 1000',
        'print board'
    ]
    output = StringIO()

    board = run(lines, output=output)

    assert output.getvalue() == '. wR .\n'
    assert board == [['.', 'wR', '.']]
