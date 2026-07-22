from client.game_view_state import GameViewState
from events.game_animations import GAME_END_ANIMATION, GameAnimationCues
from events.sound import CAPTURE_CUE, GAME_END_CUE, JUMP_CUE, MOVE_CUE, SoundCues
from model.piece import BLACK, WHITE


def _snapshot_payload():
    return {
        "board_width": 3,
        "board_height": 3,
        "game_over": False,
        "selected_cell": None,
        "pieces": [],
        "move_log": {WHITE: [], BLACK: []},
        "score": {WHITE: 0, BLACK: 0},
    }


def make_state():
    return GameViewState(_snapshot_payload())


def test_a_snapshot_message_updates_the_board_and_panel_state():
    state = make_state()
    payload = _snapshot_payload()
    payload["pieces"] = [
        {
            "id": "p1",
            "kind": "rook",
            "color": WHITE,
            "row": 0,
            "col": 0,
            "state": "idle",
            "motion_phase": "idle",
            "cooldown_remaining_ms": 0,
            "cooldown_total_ms": 0,
        }
    ]
    payload["move_log"][WHITE] = [{"notation": "a1a2", "elapsed_ms": 5}]

    state.apply_message(payload)

    assert len(state.snapshot.pieces) == 1
    assert state.panel_state.entries_for(WHITE)[0].notation == "a1a2"


def test_move_logged_with_is_jump_false_plays_the_move_cue():
    state = make_state()
    sound = SoundCues(state.bus)

    state.apply_message({"type": "move_logged", "is_jump": False})

    assert sound.played == [MOVE_CUE]


def test_move_logged_with_is_jump_true_plays_the_jump_cue():
    state = make_state()
    sound = SoundCues(state.bus)

    state.apply_message({"type": "move_logged", "is_jump": True})

    assert sound.played == [JUMP_CUE]


def test_capture_plays_the_capture_cue():
    state = make_state()
    sound = SoundCues(state.bus)

    state.apply_message({"type": "capture"})

    assert sound.played == [CAPTURE_CUE]


def test_a_capturing_move_plays_both_cues_in_wire_order():
    # A capturing move arrives as two separate wire messages (see
    # server/session.py's drain_wire_events) - the same two cues a real
    # GameEngine-fed Bus would produce for the same capture (see
    # events/sound.py's SoundCues), not a single mutually-exclusive choice.
    state = make_state()
    sound = SoundCues(state.bus)

    state.apply_message({"type": "move_logged", "is_jump": False})
    state.apply_message({"type": "capture"})

    assert sound.played == [MOVE_CUE, CAPTURE_CUE]


def test_game_over_fires_a_game_ended_event():
    state = make_state()
    sound = SoundCues(state.bus)
    animations = GameAnimationCues(state.bus)

    state.apply_message({"type": "game_over", "ratings": {WHITE: 1210, BLACK: 1190}})

    assert sound.played == [GAME_END_CUE]
    assert animations.triggered == [GAME_END_ANIMATION]


def test_disconnect_countdown_sets_the_status_message():
    state = make_state()

    state.apply_message({"type": "disconnect_countdown", "seat": WHITE, "seconds_remaining": 7})

    assert state.status_message == "Opponent disconnected - resigning in 7s unless they return"


def test_a_rejected_ack_sets_the_status_message():
    state = make_state()

    state.apply_message({"type": "ack", "accepted": False, "reason": "route_conflict"})

    assert state.status_message == "Illegal move: route_conflict"


def test_an_accepted_ack_leaves_the_status_message_untouched():
    state = make_state()

    state.apply_message({"type": "ack", "accepted": True, "reason": "ok"})

    assert state.status_message is None


def test_status_message_prefers_the_disconnect_countdown_over_a_rejected_move():
    state = make_state()

    state.apply_message({"type": "ack", "accepted": False, "reason": "route_conflict"})
    state.apply_message({"type": "disconnect_countdown", "seat": WHITE, "seconds_remaining": 7})

    assert state.status_message == "Opponent disconnected - resigning in 7s unless they return"


def test_end_batch_clears_a_stale_disconnect_countdown_once_a_snapshot_arrives_without_one():
    # A tick that broadcasts a snapshot but no accompanying
    # disconnect_countdown means the opponent's seat is no longer
    # disconnected (see server/ws_server.py's _advance_game).
    state = make_state()
    state.begin_batch()
    state.apply_message({"type": "disconnect_countdown", "seat": WHITE, "seconds_remaining": 7})
    state.end_batch()
    assert state.status_message is not None

    state.begin_batch()
    state.apply_message(_snapshot_payload())
    state.end_batch()

    assert state.status_message is None


def test_end_batch_keeps_the_disconnect_countdown_while_still_being_rebroadcast():
    state = make_state()
    state.begin_batch()
    state.apply_message(_snapshot_payload())
    state.apply_message({"type": "disconnect_countdown", "seat": WHITE, "seconds_remaining": 7})
    state.end_batch()

    assert state.status_message is not None
