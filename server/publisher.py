"""Bridges one GameSession's own domain-event Bus onto the wire, so
GameSession itself never has to import protocol/game_messages.py at all -
see server/session.py's own docstring on why it claims no notion of
websockets or broadcasting; before this existed, it quietly broke that
claim by building MoveLoggedMessage/CaptureMessage (wire dataclasses)
into its own _pending_wire_events buffer.

Subscribes directly to the same Bus GameSession already publishes
MoveLoggedEvent/ArrivalEvent onto for its move-log/score observers (see
GameSession.__init__) - this is just one more subscriber, translating each
into the wire message server/game_loop.py's own tick loop broadcasts, the
same "domain event in, wire message out" role their own NetworkPublisher
plays.
"""

from typing import List, Union

from events.bus import Bus
from model.game_state import ArrivalEvent, MoveLoggedEvent
from protocol.game_messages import CaptureMessage, MoveLoggedMessage


class NetworkPublisher:
    def __init__(self, bus: Bus):
        self._pending: List[Union[MoveLoggedMessage, CaptureMessage]] = []
        bus.subscribe(MoveLoggedEvent, self._on_move_logged)
        bus.subscribe(ArrivalEvent, self._on_arrival)

    def _on_move_logged(self, event: MoveLoggedEvent) -> None:
        self._pending.append(MoveLoggedMessage(is_jump=event.is_jump))

    # Fires on every arrival, but only ever buffered for a capture - a
    # networked client's SoundCues only reacts to ArrivalEvent.captured_piece
    # being non-None (see events/sound.py's SoundCues._on_arrival), so a
    # quiet arrival has nothing worth telling it about.
    def _on_arrival(self, event: ArrivalEvent) -> None:
        if event.captured_piece is not None:
            self._pending.append(CaptureMessage())

    # Drains every wire event buffered since the last call, in order - see
    # server/game_loop.py's _advance_game, the only caller, once per tick.
    def drain(self) -> List[Union[MoveLoggedMessage, CaptureMessage]]:
        events = self._pending
        self._pending = []
        return events
