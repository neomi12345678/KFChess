"""A logged-in connection's high-level status - computed on demand from
whichever registry actually owns that fact (server/matchmaking.py's
MatchmakingQueue, server/rooms.py's RoomRegistry, server/game_loop.py's
GameLoop), not stored as a separate field of its own. Those three registries
are already each the single source of truth for their own slice of state; a
fourth, independently-maintained "current status" field would only risk
drifting out of sync with them the moment some call site forgot to update
it on a transition. server/router.py's CommandRouter is the only caller -
participant_state() below is the one place that combines all three, so
nothing else re-derives "is this username already busy" by hand.
"""

from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from server.game_loop import GameLoop
    from server.rooms import RoomRegistry


class ParticipantState(str, Enum):
    SEARCHING = "searching"
    IN_ROOM = "in_room"

    def __str__(self) -> str:
        return self.value


# None means free to start something new (PLAY/CREATE_ROOM/JOIN_ROOM) - the
# same "not busy" case the wire-level *_ack "reason" fields need. IN_ROOM
# covers both an active game (seated or spectating) and a still-pending
# room, checked first since it's the more specific fact; SEARCHING is only
# ever true once IN_ROOM is ruled out (a username can't be both, see
# server/matchmaking.py's/server/rooms.py's own "one at a time" rules).
def participant_state(username: str, game_loop: "GameLoop", rooms: "RoomRegistry") -> Optional[ParticipantState]:
    if game_loop.active_game_for(username) is not None or rooms.room_for_username(username) is not None:
        return ParticipantState.IN_ROOM
    if game_loop.matchmaking.is_waiting(username):
        return ParticipantState.SEARCHING
    return None
