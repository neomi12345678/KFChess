"""Room registry for the Home screen's "Room" flow (create an id, join it,
cancel it) - the section-6 counterpart to server/matchmaking.py's
ELO-proximity PLAY queue: pure bookkeeping, no I/O. server/ws_server.py
owns the actual connections and starts a GameSession once a room's second
seat fills; this only ever tracks which rooms exist, who's in them, and
decides whether a joiner becomes the opponent or a spectator.
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

_ID_LENGTH = 6


@dataclass
class Room:
    room_id: str
    creator: str
    opponent: Optional[str] = None
    spectators: Set[str] = field(default_factory=set)

    # A room stops being "joinable as the opponent" the instant a second
    # player fills it - every joiner after that is a spectator instead
    # (see RoomRegistry.join), and it's no longer cancellable (see
    # RoomRegistry.cancel) since a real game is what's now in progress.
    @property
    def is_pending(self) -> bool:
        return self.opponent is None


class RoomError(Exception):
    """Raised for a room request that can't be granted - not found, the
    caller's already elsewhere, wrong creator, already started. str(error)
    is itself the wire-ready reason code (see server/ws_server.py's
    *_room_ack handlers), the same role server/accounts.py's
    InvalidCredentialsError plays for login."""


class RoomRegistry:
    def __init__(self):
        self._rooms: Dict[str, Room] = {}
        # A username is creator/opponent/spectator of at most one room at a
        # time - mirrors server/matchmaking.py's own "already queued" rule,
        # same reasoning: one connection, one concurrent game.
        self._room_id_by_username: Dict[str, str] = {}

    def create(self, username: str) -> Room:
        if username in self._room_id_by_username:
            raise RoomError("already_in_a_room")

        room = Room(room_id=self._new_id(), creator=username)
        self._rooms[room.room_id] = room
        self._room_id_by_username[username] = room.room_id
        return room

    # The first join fills the opponent seat; every join after that is a
    # spectator - RoomRegistry itself doesn't care which, only reports it
    # back via the returned Room's own opponent/spectators (see
    # server/ws_server.py's _handle_join_room, which reads room.opponent ==
    # username to tell the two cases apart).
    def join(self, room_id: str, username: str) -> Room:
        room = self._rooms.get(room_id)
        if room is None:
            raise RoomError("room_not_found")
        if username in self._room_id_by_username:
            raise RoomError("already_in_a_room")

        if room.is_pending:
            room.opponent = username
        else:
            room.spectators.add(username)
        self._room_id_by_username[username] = room_id
        return room

    # Only the creator, and only before an opponent has joined - once a
    # room has a real game running, leaving it is a resignation/disconnect
    # (see server/session.py's own disconnect-grace handling), not a
    # cancellation.
    def cancel(self, username: str) -> None:
        room = self.room_for_username(username)
        if room is None:
            raise RoomError("not_in_a_room")
        if room.creator != username:
            raise RoomError("not_the_creator")
        if not room.is_pending:
            raise RoomError("already_started")

        self._forget(room)

    def room_for_username(self, username: str) -> Optional[Room]:
        room_id = self._room_id_by_username.get(username)
        return self._rooms.get(room_id) if room_id is not None else None

    # Called once the room's own game actually ends (see
    # server/ws_server.py's _advance_game) - frees every member (creator,
    # opponent, every spectator) to create or join a new room, and drops
    # the room itself from the registry. A no-op if the room is already
    # gone (cancel() may have removed it already), same defensiveness as
    # server/matchmaking.py's own remove().
    def close(self, room_id: str) -> None:
        room = self._rooms.get(room_id)
        if room is not None:
            self._forget(room)

    def _forget(self, room: Room) -> None:
        del self._rooms[room.room_id]
        self._room_id_by_username.pop(room.creator, None)
        if room.opponent is not None:
            self._room_id_by_username.pop(room.opponent, None)
        for spectator in room.spectators:
            self._room_id_by_username.pop(spectator, None)

    # Short and arbitrary (see the Home-screen slide's own room-id wording)
    # - collisions are checked and retried rather than assumed impossible,
    # the same defensiveness server/accounts.py's random salt doesn't need
    # (a salt has no uniqueness requirement at all) but a shared, guessable
    # keyspace like this one does.
    def _new_id(self) -> str:
        while True:
            candidate = uuid.uuid4().hex[:_ID_LENGTH]
            if candidate not in self._rooms:
                return candidate
