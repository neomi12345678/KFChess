import pytest

from client.client_cli import InputError, _ClientState, build_command
from client.network_client import SnapshotBroadcast
from model.piece import BLACK, WHITE
from protocol.game_messages import AckMessage, GameOverMessage, JumpMessage, MoveMessage, SeatMessage


def test_build_command_reads_a_move_for_the_seats_own_color():
    command = build_command("e2e4", WHITE, board_height=8)

    assert command == MoveMessage(color=WHITE, source={"row": 6, "col": 4}, destination={"row": 4, "col": 4})


def test_build_command_reads_a_black_seats_move():
    command = build_command("g8f6", BLACK, board_height=8)

    assert command == MoveMessage(color=BLACK, source={"row": 0, "col": 6}, destination={"row": 2, "col": 5})


def test_build_command_strips_surrounding_whitespace():
    command = build_command("  e2e4  ", WHITE, board_height=8)

    assert command == MoveMessage(color=WHITE, source={"row": 6, "col": 4}, destination={"row": 4, "col": 4})


def test_build_command_translates_jump_shorthand():
    expected = JumpMessage(color=WHITE, source={"row": 4, "col": 4})

    assert build_command("jump e4", WHITE, board_height=8) == expected
    assert build_command("JUMP e4", WHITE, board_height=8) == expected


def test_build_command_rejects_empty_input():
    with pytest.raises(InputError):
        build_command("", WHITE, board_height=8)

    with pytest.raises(InputError):
        build_command("   ", WHITE, board_height=8)


def test_build_command_rejects_a_jump_with_no_square():
    with pytest.raises(InputError):
        build_command("jump", WHITE, board_height=8)

    with pytest.raises(InputError):
        build_command("jump   ", WHITE, board_height=8)


def test_build_command_rejects_a_malformed_square():
    with pytest.raises(InputError):
        build_command("jump 2e", WHITE, board_height=8)

    with pytest.raises(InputError):
        build_command("2ee4", WHITE, board_height=8)


def test_client_state_starts_with_no_seat_or_board_height_by_default():
    state = _ClientState()

    assert state.seat is None
    assert state.board_height is None


def test_client_state_learns_its_seat_from_a_seat_message():
    state = _ClientState()

    state.observe(SeatMessage(color=WHITE))

    assert state.seat == WHITE


def test_client_state_clears_its_seat_when_the_game_ends():
    state = _ClientState(seat=WHITE)

    state.observe(GameOverMessage(ratings={"white": 1216, "black": 1184}))

    assert state.seat is None


def test_client_state_ignores_unrelated_messages():
    state = _ClientState(seat=WHITE)

    state.observe(AckMessage(accepted=True, reason="ok"))

    assert state.seat == WHITE


def test_client_state_learns_board_height_from_a_snapshot_broadcast():
    state = _ClientState()

    state.observe(
        SnapshotBroadcast(
            payload={"board_width": 8, "board_height": 8, "pieces": [], "selected_cell": None, "game_over": False}
        )
    )

    assert state.board_height == 8
