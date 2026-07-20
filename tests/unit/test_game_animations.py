from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, KING, PAWN, ROOK, WHITE, Piece
from model.position import Position
from events.bus import Bus
from events.game_animations import GAME_END_ANIMATION, GAME_START_ANIMATION, GameAnimationCues
from events.game_events import GameEndedEvent, GameStartedEvent


def make_piece(color, kind):
    return Piece(id=f"{color}-{kind}", color=color, kind=kind, cell=Position(0, 0))


def test_game_started_triggers_the_start_animation():
    bus = Bus()
    animations = GameAnimationCues(bus)

    bus.publish(GameStartedEvent())

    assert animations.triggered == [GAME_START_ANIMATION]


def test_game_ended_triggers_the_end_animation():
    bus = Bus()
    animations = GameAnimationCues(bus)
    arrival = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=make_piece(BLACK, KING))

    bus.publish(GameEndedEvent(arrival=arrival))

    assert animations.triggered == [GAME_END_ANIMATION]


def test_move_logged_and_arrival_trigger_nothing():
    bus = Bus()
    animations = GameAnimationCues(bus)
    move_event = MoveLoggedEvent(
        piece_id="mover",
        color=WHITE,
        kind=PAWN,
        source=Position(1, 1),
        destination=Position(0, 1),
        is_capture=False,
        is_jump=False,
        elapsed_ms=0,
    )
    arrival_event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=None)

    bus.publish(move_event)
    bus.publish(arrival_event)

    assert animations.triggered == []
