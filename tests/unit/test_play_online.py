from events.bus import Bus
from events.sound import CAPTURE_CUE, JUMP_CUE, MOVE_CUE, SoundCues
from model.piece import BLACK, WHITE
from play_online import _publish_move_events
from server.protocol import PanelState


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


def _sound_cues_played(panel_state, counts):
    bus = Bus()
    sound = SoundCues(bus)
    _publish_move_events(bus, panel_state, counts)
    return sound.played


def test_publish_move_events_is_silent_when_nothing_new_arrived():
    panel_state = _panel_state_with(["e4"])
    counts = {WHITE: 1, BLACK: 0}

    assert _sound_cues_played(panel_state, counts) == []


def test_publish_move_events_reports_one_new_plain_move():
    panel_state = _panel_state_with(["e4"])
    counts = {WHITE: 0, BLACK: 0}

    assert _sound_cues_played(panel_state, counts) == [MOVE_CUE]
    assert counts[WHITE] == 1


def test_publish_move_events_reports_a_capture_and_a_jump_distinctly():
    panel_state = _panel_state_with(["e4", "exd5"], ["Nf3^"])
    counts = {WHITE: 0, BLACK: 0}

    cues = _sound_cues_played(panel_state, counts)

    # A capturing move logs both its MoveLoggedEvent (MOVE_CUE, since it
    # isn't a jump) and an ArrivalEvent (CAPTURE_CUE) - the same two cues
    # a real GameEngine-fed Bus would produce for the same capture (see
    # events/sound.py's SoundCues), not a single mutually-exclusive choice.
    assert cues == [MOVE_CUE, MOVE_CUE, CAPTURE_CUE, JUMP_CUE]
    assert counts == {WHITE: 2, BLACK: 1}


def test_publish_move_events_updates_counts_so_a_second_call_reports_nothing_new():
    panel_state = _panel_state_with(["e4"])
    counts = {WHITE: 0, BLACK: 0}
    bus = Bus()
    sound = SoundCues(bus)

    _publish_move_events(bus, panel_state, counts)
    _publish_move_events(bus, panel_state, counts)

    assert sound.played == [MOVE_CUE]


def test_publish_move_events_seeded_from_a_nonzero_starting_count_ignores_earlier_entries():
    # Mirrors a mid-game reconnect: the move log already has entries the
    # very first snapshot brings in, and none of those already-happened
    # moves should be reported as "new".
    panel_state = _panel_state_with(["e4", "e5", "Nf3"])
    counts = {WHITE: 2, BLACK: 1}

    assert _sound_cues_played(panel_state, counts) == [MOVE_CUE]
    assert counts[WHITE] == 3
