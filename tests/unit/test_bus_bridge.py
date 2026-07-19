from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, KING, PAWN, ROOK, WHITE, Piece
from model.position import Position
from events.bus import ARRIVAL, GAME_ENDED, MOVE_LOGGED, Bus
from events.bus_bridge import BusBridge


def make_piece(color, kind, row=0, col=0):
    return Piece(id=f"{color}-{kind}-{row}{col}", color=color, kind=kind, cell=Position(row, col))


def make_move_event(color=WHITE, kind=PAWN, is_jump=False):
    return MoveLoggedEvent(
        piece_id="mover",
        color=color,
        kind=kind,
        source=Position(1, 1),
        destination=Position(0, 1),
        is_capture=False,
        is_jump=is_jump,
        elapsed_ms=0,
    )


def test_on_move_logged_publishes_to_move_logged_with_the_same_event():
    bus = Bus()
    received = []
    bus.subscribe(MOVE_LOGGED, received.append)
    bridge = BusBridge(bus)
    event = make_move_event()

    bridge.on_move_logged(event)

    assert received == [event]


def test_on_arrival_publishes_to_arrival_with_the_same_event():
    bus = Bus()
    received = []
    bus.subscribe(ARRIVAL, received.append)
    bridge = BusBridge(bus)
    event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=None)

    bridge.on_arrival(event)

    assert received == [event]


def test_on_arrival_with_a_king_capture_also_publishes_game_ended():
    bus = Bus()
    ended = []
    bus.subscribe(GAME_ENDED, ended.append)
    bridge = BusBridge(bus)
    king = make_piece(BLACK, KING)
    event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=king)

    bridge.on_arrival(event)

    assert ended == [event]


def test_on_arrival_without_a_capture_does_not_publish_game_ended():
    bus = Bus()
    ended = []
    bus.subscribe(GAME_ENDED, ended.append)
    bridge = BusBridge(bus)
    event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=None)

    bridge.on_arrival(event)

    assert ended == []


def test_on_arrival_with_a_non_king_capture_does_not_publish_game_ended():
    bus = Bus()
    ended = []
    bus.subscribe(GAME_ENDED, ended.append)
    bridge = BusBridge(bus)
    event = ArrivalEvent(piece=make_piece(WHITE, ROOK), captured_piece=make_piece(BLACK, PAWN))

    bridge.on_arrival(event)

    assert ended == []
