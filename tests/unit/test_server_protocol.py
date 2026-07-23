import pytest

from events.observers import MoveLogObserver, ScoreObserver
from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, KNIGHT, PAWN, Piece, WHITE
from model.position import Position
from protocol.panel_state import PanelState
from protocol.snapshot_codec import panel_to_json, snapshot_from_json, snapshot_to_json
from server.protocol import (
    JUMP,
    MOVE,
    LoginRequest,
    ProtocolError,
    is_cancel_room_command,
    is_create_room_command,
    is_play_command,
    parse_command,
    parse_join_room,
    parse_login,
    parse_square,
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


def test_is_create_room_command_recognizes_the_bare_keyword():
    assert is_create_room_command("CREATE_ROOM") is True
    assert is_create_room_command("  CREATE_ROOM  ") is True


def test_is_create_room_command_rejects_anything_else():
    assert is_create_room_command("create_room") is False
    assert is_create_room_command("PLAY") is False


def test_is_cancel_room_command_recognizes_the_bare_keyword():
    assert is_cancel_room_command("CANCEL_ROOM") is True
    assert is_cancel_room_command("  CANCEL_ROOM  ") is True


def test_is_cancel_room_command_rejects_anything_else():
    assert is_cancel_room_command("cancel_room") is False
    assert is_cancel_room_command("PLAY") is False


def test_parse_join_room_reads_the_room_id():
    assert parse_join_room("JOIN_ROOM ab12cd") == "ab12cd"


def test_parse_join_room_returns_none_for_a_non_join_room_message():
    assert parse_join_room("PLAY") is None
    assert parse_join_room("We2e4") is None
    # No trailing space at all - not recognized as this message shape,
    # the same way parse_login treats a bare "LOGIN" with no space.
    assert parse_join_room("JOIN_ROOM") is None


def test_parse_join_room_rejects_a_missing_id():
    with pytest.raises(ProtocolError):
        parse_join_room("JOIN_ROOM ")

    with pytest.raises(ProtocolError):
        parse_join_room("JOIN_ROOM    ")


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
                "cooldown_remaining_ms": 0,
                "cooldown_total_ms": 0,
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


def test_panel_to_json_is_plain_json_serializable_data():
    move_log = MoveLogObserver(board_height=8)
    move_log.on_move_logged(
        MoveLoggedEvent(
            piece_id="wP-6-4", color=WHITE, kind=PAWN, source=Position(6, 4), destination=Position(4, 4),
            is_capture=False, is_jump=False, elapsed_ms=4105,
        )
    )
    score = ScoreObserver()
    score.on_arrival(ArrivalEvent(piece=Piece(id="wN", color=WHITE, kind=KNIGHT, cell=Position(5, 2)),
                                   captured_piece=Piece(id="bP", color=BLACK, kind=PAWN, cell=Position(5, 2))))

    payload = panel_to_json(move_log, score, names={WHITE: "alice", BLACK: "bob"})

    assert payload == {
        "move_log": {
            WHITE: [{"notation": "e4", "elapsed_ms": 4105}],
            BLACK: [],
        },
        "score": {WHITE: 1, BLACK: 0},
        "names": {WHITE: "alice", BLACK: "bob"},
    }


def test_panel_to_json_defaults_names_to_empty_when_none_are_given():
    move_log = MoveLogObserver(board_height=8)
    score = ScoreObserver()

    payload = panel_to_json(move_log, score)

    assert payload["names"] == {}


def test_panel_state_reconstructs_entries_for_and_score_for_from_the_wire_payload():
    move_log = MoveLogObserver(board_height=8)
    move_log.on_move_logged(
        MoveLoggedEvent(
            piece_id="wP-6-4", color=WHITE, kind=PAWN, source=Position(6, 4), destination=Position(4, 4),
            is_capture=False, is_jump=False, elapsed_ms=4105,
        )
    )
    score = ScoreObserver()
    score.on_arrival(ArrivalEvent(piece=Piece(id="wN", color=WHITE, kind=KNIGHT, cell=Position(5, 2)),
                                   captured_piece=Piece(id="bP", color=BLACK, kind=PAWN, cell=Position(5, 2))))

    panel_state = PanelState()
    panel_state.update_from_json(panel_to_json(move_log, score, names={WHITE: "alice", BLACK: "bob"}))

    [entry] = panel_state.entries_for(WHITE)
    assert entry.notation == "e4"
    assert entry.elapsed_ms == 4105
    assert panel_state.entries_for(BLACK) == []
    assert panel_state.score_for(WHITE) == 1
    assert panel_state.score_for(BLACK) == 0
    assert panel_state.name_for(WHITE) == "alice"
    assert panel_state.name_for(BLACK) == "bob"


def test_panel_state_defaults_to_empty_before_any_update():
    panel_state = PanelState()

    assert panel_state.entries_for(WHITE) == []
    assert panel_state.score_for(WHITE) == 0
    assert panel_state.name_for(WHITE) is None


def test_panel_state_name_for_is_none_when_the_payload_carries_no_names():
    move_log = MoveLogObserver(board_height=8)
    score = ScoreObserver()
    panel_state = PanelState()

    panel_state.update_from_json(panel_to_json(move_log, score))

    assert panel_state.name_for(WHITE) is None
