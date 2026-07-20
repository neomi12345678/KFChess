from events.sound import CAPTURE_CUE, JUMP_CUE, MOVE_CUE
from model.piece import BLACK, WHITE
from play_online import _cue_for_notation, _new_move_cues
from server.protocol import PanelState


def test_cue_for_notation_plain_move_is_the_move_cue():
    assert _cue_for_notation("e4") == MOVE_CUE
    assert _cue_for_notation("Nf3") == MOVE_CUE


def test_cue_for_notation_capture_is_the_capture_cue():
    assert _cue_for_notation("exd5") == CAPTURE_CUE
    assert _cue_for_notation("Rxb1") == CAPTURE_CUE


def test_cue_for_notation_jump_is_the_jump_cue():
    assert _cue_for_notation("e4^") == JUMP_CUE
    assert _cue_for_notation("Ne4^") == JUMP_CUE


def _panel_state_with(white_notations, black_notations=()):
    panel_state = PanelState()
    panel_state.update_from_json(
        {
            "move_log": {
                WHITE: [{"notation": n, "elapsed_ms": 0} for n in white_notations],
                BLACK: [{"notation": n, "elapsed_ms": 0} for n in black_notations],
            },
            "score": {WHITE: 0, BLACK: 0},
        }
    )
    return panel_state


def test_new_move_cues_is_empty_when_nothing_new_arrived():
    panel_state = _panel_state_with(["e4"])
    counts = {WHITE: 1, BLACK: 0}

    assert _new_move_cues(panel_state, counts) == []


def test_new_move_cues_reports_one_new_entry():
    panel_state = _panel_state_with(["e4"])
    counts = {WHITE: 0, BLACK: 0}

    assert _new_move_cues(panel_state, counts) == [MOVE_CUE]
    assert counts[WHITE] == 1


def test_new_move_cues_reports_a_capture_and_a_jump_distinctly():
    panel_state = _panel_state_with(["e4", "exd5"], ["Nf3^"])
    counts = {WHITE: 0, BLACK: 0}

    cues = _new_move_cues(panel_state, counts)

    assert cues == [MOVE_CUE, CAPTURE_CUE, JUMP_CUE]
    assert counts == {WHITE: 2, BLACK: 1}


def test_new_move_cues_updates_counts_so_a_second_call_sees_nothing_new():
    panel_state = _panel_state_with(["e4"])
    counts = {WHITE: 0, BLACK: 0}

    _new_move_cues(panel_state, counts)
    second_call = _new_move_cues(panel_state, counts)

    assert second_call == []


def test_new_move_cues_seeded_from_a_nonzero_starting_count_ignores_earlier_entries():
    # Mirrors a mid-game reconnect: the move log already has entries the
    # very first snapshot brings in, and none of those already-happened
    # moves should be reported as "new".
    panel_state = _panel_state_with(["e4", "e5", "Nf3"])
    counts = {WHITE: 2, BLACK: 1}

    assert _new_move_cues(panel_state, counts) == [MOVE_CUE]
    assert counts[WHITE] == 3
