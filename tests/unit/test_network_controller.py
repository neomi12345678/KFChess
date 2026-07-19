from model.game_state import GameSnapshot, PieceSnapshot
from model.piece import BLACK, KING, PHASE_IDLE, PHASE_MOVE, ROOK, WHITE
from model.position import Position
from server.network_controller import JumpRequest, MoveRequest, NetworkController


def make_piece(piece_id, color, kind=ROOK, row=0, col=0, motion_phase=PHASE_IDLE):
    return PieceSnapshot(id=piece_id, kind=kind, color=color, row=float(row), col=float(col), state="idle", motion_phase=motion_phase)


def make_snapshot(pieces, board_width=3, board_height=3, game_over=False):
    return GameSnapshot(
        board_width=board_width, board_height=board_height, pieces=tuple(pieces), selected_cell=None, game_over=game_over
    )


def test_first_click_on_an_own_idle_piece_selects_it():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0)])

    result = controller.click(Position(0, 0), snapshot)

    assert controller.selected == Position(0, 0)
    assert result is None


def test_first_click_on_an_empty_cell_leaves_selection_empty():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([])

    controller.click(Position(0, 0), snapshot)

    assert controller.selected is None


def test_first_click_on_an_opponent_piece_does_not_select_it():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("b1", BLACK, row=0, col=0)])

    controller.click(Position(0, 0), snapshot)

    assert controller.selected is None


def test_first_click_on_a_non_idle_own_piece_does_not_select_it():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0, motion_phase=PHASE_MOVE)])

    controller.click(Position(0, 0), snapshot)

    assert controller.selected is None


def test_click_with_no_resolved_cell_and_no_selection_does_nothing():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([])

    result = controller.click(None, snapshot)

    assert controller.selected is None
    assert result is None


def test_click_with_no_resolved_cell_cancels_an_existing_selection():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0)])
    controller.click(Position(0, 0), snapshot)

    controller.click(None, snapshot)

    assert controller.selected is None


def test_second_click_on_an_empty_cell_returns_a_move_request_and_clears_selection():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0)])
    controller.click(Position(0, 0), snapshot)

    result = controller.click(Position(0, 2), snapshot)

    assert result == MoveRequest(source=Position(0, 0), destination=Position(0, 2))
    assert controller.selected is None


def test_second_click_on_an_enemy_piece_still_returns_a_move_request():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0), make_piece("b1", BLACK, row=0, col=2)])
    controller.click(Position(0, 0), snapshot)

    result = controller.click(Position(0, 2), snapshot)

    assert result == MoveRequest(source=Position(0, 0), destination=Position(0, 2))


def test_clicking_another_own_idle_piece_switches_selection_instead_of_moving():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0), make_piece("w2", WHITE, kind=KING, row=0, col=2)])
    controller.click(Position(0, 0), snapshot)

    result = controller.click(Position(0, 2), snapshot)

    assert controller.selected == Position(0, 2)
    assert result is None


def test_clicking_a_friendly_piece_that_is_busy_preserves_the_original_selection():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot(
        [
            make_piece("w1", WHITE, row=0, col=0),
            make_piece("w2", WHITE, kind=KING, row=0, col=2, motion_phase=PHASE_MOVE),
        ]
    )
    controller.click(Position(0, 0), snapshot)

    result = controller.click(Position(0, 2), snapshot)

    assert controller.selected == Position(0, 0)
    assert result is None


def test_second_click_is_ignored_when_a_different_piece_now_occupies_the_selected_cell():
    controller = NetworkController(WHITE)
    snapshot_a = make_snapshot([make_piece("w1", WHITE, row=0, col=0)])
    controller.click(Position(0, 0), snapshot_a)
    assert controller.selected == Position(0, 0)

    # Real wall-clock time passes between two clicks - the originally
    # selected piece may have been replaced by a different one landing on
    # the same cell (see server/network_controller.py's own docstring).
    snapshot_b = make_snapshot([make_piece("impostor", WHITE, row=0, col=0)])

    result = controller.click(Position(0, 2), snapshot_b)

    assert controller.selected is None
    assert result is None


def test_jump_returns_a_jump_request_for_the_clicked_cell():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0)])

    result = controller.jump(Position(0, 0))

    assert result == JumpRequest(position=Position(0, 0))


def test_jump_with_no_resolved_cell_is_ignored():
    controller = NetworkController(WHITE)

    result = controller.jump(None)

    assert result is None


def test_jump_clears_a_leftover_selection_from_an_earlier_click():
    controller = NetworkController(WHITE)
    snapshot = make_snapshot([make_piece("w1", WHITE, row=0, col=0), make_piece("b1", BLACK, row=0, col=2)])
    controller.click(Position(0, 0), snapshot)
    assert controller.selected == Position(0, 0)

    controller.jump(Position(0, 2))

    assert controller.selected is None
