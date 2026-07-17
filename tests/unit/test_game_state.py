from model.game_state import ArrivalEvent, GameObserver, MoveLoggedEvent
from model.piece import PAWN, Piece, WHITE
from model.position import Position


def test_game_observer_default_hooks_are_no_ops_a_bare_instance_can_receive():
    # A concrete observer only overrides the hook(s) it cares about (see
    # events/observers.py) - the base class itself must tolerate being
    # notified of both events and simply do nothing.
    observer = GameObserver()
    piece = Piece(id="p1", color=WHITE, kind=PAWN, cell=Position(0, 0))
    event = MoveLoggedEvent(
        color=WHITE, kind=PAWN, source=Position(1, 0), destination=Position(0, 0),
        is_capture=False, is_jump=False, elapsed_ms=0,
    )

    observer.on_move_logged(event)
    observer.on_arrival(ArrivalEvent(piece=piece, captured_piece=None))
