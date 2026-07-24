from events.observers import MoveLogObserver, ScoreObserver
from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, KNIGHT, PAWN, Piece, WHITE
from model.position import Position
from protocol.game_messages import build_jump, build_move
from protocol.panel_state import PanelState
from protocol.snapshot_codec import panel_to_json, snapshot_from_json, snapshot_to_json
from server.protocol import JUMP, MOVE, command_from_message


def test_command_from_message_reads_a_move_messages_color_source_and_destination():
    message = build_move(WHITE, Position(6, 4), Position(4, 4))

    command = command_from_message(message)

    assert command.color == WHITE
    assert command.kind == MOVE
    assert command.source == Position(6, 4)
    assert command.destination == Position(4, 4)


def test_command_from_message_jump_has_no_destination():
    message = build_jump(WHITE, Position(4, 4))

    command = command_from_message(message)

    assert command.color == WHITE
    assert command.kind == JUMP
    assert command.source == Position(4, 4)
    assert command.destination is None


def test_command_from_message_black_color():
    message = build_move(BLACK, Position(0, 6), Position(2, 5))

    command = command_from_message(message)

    assert command.color == BLACK
    assert command.source == Position(0, 6)
    assert command.destination == Position(2, 5)


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
