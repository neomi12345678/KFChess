import pytest

from model.piece import BLACK, WHITE
from model.position import Position
from server.protocol import (
    JUMP,
    MOVE,
    LoginRequest,
    ProtocolError,
    is_play_command,
    parse_command,
    parse_login,
    parse_square,
    snapshot_from_json,
    snapshot_to_json,
)


def test_parse_square_matches_standard_chess_e2():
    # board_height=8, matching a standard 8x8 board - row 0 is rank 8 (see
    # boardio.algebraic_notation.square_name's own convention), so "e2" is
    # row 6, the white pawns' starting rank.
    assert parse_square("e2", board_height=8) == Position(6, 4)


def test_parse_square_matches_standard_chess_e4():
    assert parse_square("e4", board_height=8) == Position(4, 4)


def test_parse_square_rejects_malformed_input():
    with pytest.raises(ProtocolError):
        parse_square("2e", board_height=8)

    with pytest.raises(ProtocolError):
        parse_square("e", board_height=8)


def test_parse_command_move_reads_color_source_and_destination():
    command = parse_command("We2e4", board_height=8)

    assert command.color == WHITE
    assert command.kind == MOVE
    assert command.source == Position(6, 4)
    assert command.destination == Position(4, 4)


def test_parse_command_move_handles_double_digit_ranks_on_a_taller_board():
    # board_height=10 has ranks up to 10, so the source/destination split
    # can't just assume a single trailing digit.
    command = parse_command("Wa10a9", board_height=10)

    assert command.source == Position(0, 0)
    assert command.destination == Position(1, 0)


def test_parse_command_jump_has_no_destination():
    command = parse_command("WJe4", board_height=8)

    assert command.color == WHITE
    assert command.kind == JUMP
    assert command.source == Position(4, 4)
    assert command.destination is None


def test_parse_command_black_color_prefix():
    command = parse_command("Bg8f6", board_height=8)

    assert command.color == BLACK
    assert command.source == Position(0, 6)
    assert command.destination == Position(2, 5)


def test_parse_command_rejects_unknown_color_prefix():
    with pytest.raises(ProtocolError):
        parse_command("Xe2e4", board_height=8)


def test_parse_command_rejects_too_short_input():
    with pytest.raises(ProtocolError):
        parse_command("W", board_height=8)


def test_parse_login_reads_the_username_and_password():
    assert parse_login("LOGIN alice secret123") == LoginRequest(username="alice", password="secret123")


def test_parse_login_returns_none_for_a_non_login_message():
    assert parse_login("We2e4") is None
    assert parse_login("WJe4") is None


def test_parse_login_rejects_a_missing_password():
    with pytest.raises(ProtocolError):
        parse_login("LOGIN alice")

    with pytest.raises(ProtocolError):
        parse_login("LOGIN alice   ")


def test_parse_login_rejects_an_empty_username():
    with pytest.raises(ProtocolError):
        parse_login("LOGIN ")

    with pytest.raises(ProtocolError):
        parse_login("LOGIN    ")


def test_parse_login_keeps_internal_spaces_in_the_password():
    assert parse_login("LOGIN alice a pass with spaces") == LoginRequest(
        username="alice", password="a pass with spaces"
    )


def test_is_play_command_recognizes_the_bare_keyword():
    assert is_play_command("PLAY") is True
    assert is_play_command("  PLAY  ") is True


def test_is_play_command_rejects_anything_else():
    assert is_play_command("play") is False
    assert is_play_command("We2e4") is False
    assert is_play_command("LOGIN alice secret123") is False


def test_snapshot_to_json_is_plain_json_serializable_data():
    from model.game_state import GameSnapshot, PieceSnapshot

    snapshot = GameSnapshot(
        board_width=8,
        board_height=8,
        pieces=(
            PieceSnapshot(
                id="wP-6-4", kind="pawn", color=WHITE, row=6.0, col=4.0, state="idle", motion_phase="idle"
            ),
        ),
        selected_cell=Position(6, 4),
        game_over=False,
    )

    payload = snapshot_to_json(snapshot)

    assert payload == {
        "board_width": 8,
        "board_height": 8,
        "game_over": False,
        "selected_cell": {"row": 6, "col": 4},
        "pieces": [
            {
                "id": "wP-6-4",
                "kind": "pawn",
                "color": WHITE,
                "row": 6.0,
                "col": 4.0,
                "state": "idle",
                "motion_phase": "idle",
            }
        ],
    }


def test_snapshot_to_json_handles_no_selection():
    from model.game_state import GameSnapshot

    snapshot = GameSnapshot(board_width=8, board_height=8, pieces=(), selected_cell=None, game_over=False)

    payload = snapshot_to_json(snapshot)

    assert payload["selected_cell"] is None


def test_snapshot_from_json_is_the_inverse_of_snapshot_to_json():
    from model.game_state import GameSnapshot, PieceSnapshot

    original = GameSnapshot(
        board_width=8,
        board_height=8,
        pieces=(
            PieceSnapshot(
                id="wP-6-4", kind="pawn", color=WHITE, row=6.0, col=4.0, state="idle", motion_phase="idle"
            ),
        ),
        selected_cell=Position(6, 4),
        game_over=False,
    )

    rebuilt = snapshot_from_json(snapshot_to_json(original))

    assert rebuilt == original


def test_snapshot_from_json_handles_no_selection_and_no_pieces():
    from model.game_state import GameSnapshot

    original = GameSnapshot(board_width=3, board_height=3, pieces=(), selected_cell=None, game_over=True)

    rebuilt = snapshot_from_json(snapshot_to_json(original))

    assert rebuilt == original
