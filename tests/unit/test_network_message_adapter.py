"""NetworkMessageAdapter is the one place a decoded wire message becomes (or
doesn't become) a Bus event for the networked GUI client - a regression here
(e.g. AckMessage.accepted flipping which branch publishes) would only ever
surface as a wrong status banner during a manually-played networked game, not
a test failure, hence exercising every registered message type directly.
"""

from events.bus import Bus
from protocol.game_messages import (
    AckMessage,
    CaptureMessage,
    DisconnectCountdownMessage,
    ErrorMessage,
    GameOverMessage,
    MoveLoggedMessage,
)
from client.network_message_adapter import (
    DisconnectCountdownEvent,
    MoveRejectedEvent,
    NetworkMessageAdapter,
)
from events.game_events import GameEndedEvent, RemoteCaptureEvent, RemoteMoveEvent


def _adapter_with_capture():
    bus = Bus()
    published = []
    bus.subscribe(RemoteMoveEvent, published.append)
    bus.subscribe(RemoteCaptureEvent, published.append)
    bus.subscribe(GameEndedEvent, published.append)
    bus.subscribe(DisconnectCountdownEvent, published.append)
    bus.subscribe(MoveRejectedEvent, published.append)
    return NetworkMessageAdapter(bus), published


def test_move_logged_message_publishes_a_remote_move_event_carrying_is_jump():
    adapter, published = _adapter_with_capture()

    adapter.apply(MoveLoggedMessage(is_jump=True))

    [event] = published
    assert event == RemoteMoveEvent(is_jump=True)


def test_capture_message_publishes_a_remote_capture_event():
    adapter, published = _adapter_with_capture()

    adapter.apply(CaptureMessage())

    [event] = published
    assert event == RemoteCaptureEvent()


def test_game_over_message_publishes_a_game_ended_event_with_no_arrival_and_the_wire_ratings():
    adapter, published = _adapter_with_capture()

    adapter.apply(GameOverMessage(ratings={"W": 1210, "B": 1190}))

    [event] = published
    assert event.arrival is None
    assert event.new_ratings == {"W": 1210, "B": 1190}


def test_disconnect_countdown_message_publishes_a_disconnect_countdown_event():
    adapter, published = _adapter_with_capture()

    adapter.apply(DisconnectCountdownMessage(seat="W", seconds_remaining=7))

    [event] = published
    assert event == DisconnectCountdownEvent(seconds_remaining=7)


def test_accepted_ack_message_publishes_nothing():
    adapter, published = _adapter_with_capture()

    adapter.apply(AckMessage(accepted=True, reason=""))

    assert published == []


def test_rejected_ack_message_publishes_a_move_rejected_event_with_its_reason():
    adapter, published = _adapter_with_capture()

    adapter.apply(AckMessage(accepted=False, reason="occupied_by_own_piece"))

    [event] = published
    assert event == MoveRejectedEvent(reason="occupied_by_own_piece")


def test_a_message_with_no_registered_factory_publishes_nothing():
    adapter, published = _adapter_with_capture()

    adapter.apply(ErrorMessage(message="unrecognized message: ..."))

    assert published == []


def test_an_unrecognized_raw_dict_publishes_nothing():
    adapter, published = _adapter_with_capture()

    adapter.apply({"type": "some_future_message", "board_width": 3})

    assert published == []
