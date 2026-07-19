import pytest

from model.piece import BLACK, WHITE
from server.client_cli import InputError, _ClientState, build_command, build_login, build_play


def test_build_command_prefixes_a_move_with_the_seats_own_color_letter():
    assert build_command("e2e4", WHITE) == "We2e4"
    assert build_command("g8f6", BLACK) == "Bg8f6"


def test_build_command_strips_surrounding_whitespace():
    assert build_command("  e2e4  ", WHITE) == "We2e4"


def test_build_command_translates_jump_shorthand():
    assert build_command("jump e4", WHITE) == "WJe4"
    assert build_command("JUMP e4", WHITE) == "WJe4"


def test_build_command_rejects_empty_input():
    with pytest.raises(InputError):
        build_command("", WHITE)

    with pytest.raises(InputError):
        build_command("   ", WHITE)


def test_build_command_rejects_a_jump_with_no_square():
    with pytest.raises(InputError):
        build_command("jump", WHITE)

    with pytest.raises(InputError):
        build_command("jump   ", WHITE)


def test_build_login_wraps_the_username_and_password():
    assert build_login("alice", "secret123") == "LOGIN alice secret123"


def test_build_play_is_the_bare_keyword():
    assert build_play() == "PLAY"


def test_client_state_starts_with_no_seat_by_default():
    state = _ClientState()

    assert state.seat is None


def test_client_state_learns_its_seat_from_a_seat_message():
    state = _ClientState()

    state.observe({"type": "seat", "color": WHITE})

    assert state.seat == WHITE


def test_client_state_clears_its_seat_when_the_game_ends():
    state = _ClientState(seat=WHITE)

    state.observe({"type": "game_over", "ratings": {"white": 1216, "black": 1184}})

    assert state.seat is None


def test_client_state_ignores_unrelated_messages():
    state = _ClientState(seat=WHITE)

    state.observe({"type": "ack", "accepted": True, "reason": "ok"})

    assert state.seat == WHITE
