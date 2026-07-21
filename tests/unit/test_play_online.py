from events.bus import Bus
from events.sound import CAPTURE_CUE, JUMP_CUE, MOVE_CUE, SoundCues
from play_online import _handle_sound_event


def _sound_cues_played(*messages):
    bus = Bus()
    sound = SoundCues(bus)
    for message in messages:
        _handle_sound_event(bus, message)
    return sound.played


def test_move_logged_with_is_jump_false_plays_the_move_cue():
    assert _sound_cues_played({"type": "move_logged", "is_jump": False}) == [MOVE_CUE]


def test_move_logged_with_is_jump_true_plays_the_jump_cue():
    assert _sound_cues_played({"type": "move_logged", "is_jump": True}) == [JUMP_CUE]


def test_capture_plays_the_capture_cue():
    assert _sound_cues_played({"type": "capture"}) == [CAPTURE_CUE]


def test_a_capturing_move_plays_both_cues_in_wire_order():
    # A capturing move arrives as two separate wire messages (see
    # server/session.py's drain_wire_events) - the same two cues a real
    # GameEngine-fed Bus would produce for the same capture (see
    # events/sound.py's SoundCues), not a single mutually-exclusive choice.
    played = _sound_cues_played({"type": "move_logged", "is_jump": False}, {"type": "capture"})

    assert played == [MOVE_CUE, CAPTURE_CUE]
