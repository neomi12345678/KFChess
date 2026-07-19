from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, PAWN, ROOK, WHITE, Piece
from model.position import Position
from events.bus import ARRIVAL, GAME_ENDED, GAME_STARTED, MOVE_LOGGED, Bus
from events.sound import CAPTURE_CUE, GAME_END_CUE, GAME_START_CUE, JUMP_CUE, MOVE_CUE, SoundCues


def make_piece(color, kind):
    return Piece(id=f"{color}-{kind}", color=color, kind=kind, cell=Position(0, 0))


def make_move_event(is_jump):
    return MoveLoggedEvent(
        piece_id="mover",
        color=WHITE,
        kind=PAWN,
        source=Position(1, 1),
        destination=Position(0, 1),
        is_capture=False,
        is_jump=is_jump,
        elapsed_ms=0,
    )


def test_a_move_plays_the_move_cue():
    bus = Bus()
    sound = SoundCues(bus)

    bus.publish(MOVE_LOGGED, make_move_event(is_jump=False))

    assert sound.played == [MOVE_CUE]


def test_a_jump_plays_the_jump_cue():
    bus = Bus()
    sound = SoundCues(bus)

    bus.publish(MOVE_LOGGED, make_move_event(is_jump=True))

    assert sound.played == [JUMP_CUE]


def test_an_arrival_with_a_capture_plays_the_capture_cue():
    bus = Bus()
    sound = SoundCues(bus)
    event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=make_piece(BLACK, PAWN))

    bus.publish(ARRIVAL, event)

    assert sound.played == [CAPTURE_CUE]


def test_an_arrival_without_a_capture_plays_nothing():
    bus = Bus()
    sound = SoundCues(bus)
    event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=None)

    bus.publish(ARRIVAL, event)

    assert sound.played == []


def test_game_started_plays_the_game_start_cue():
    bus = Bus()
    sound = SoundCues(bus)

    bus.publish(GAME_STARTED)

    assert sound.played == [GAME_START_CUE]


def test_game_ended_plays_the_game_end_cue():
    bus = Bus()
    sound = SoundCues(bus)

    bus.publish(GAME_ENDED)

    assert sound.played == [GAME_END_CUE]
