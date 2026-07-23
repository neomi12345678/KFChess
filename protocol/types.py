"""Wire-level constants shared by both sides of the network connection: the
server endpoint address, the color-letter mapping command text uses (see
server/protocol.py's own import of COLOR_PREFIX), the message "type" tag
vocabulary every server->client control message carries (see
lobby_messages.py/game_messages.py), and Role, the two things a successful
JOIN_ROOM can seat a connection as.
"""

from enum import Enum

from model.piece import BLACK, WHITE

# The real, well-known server endpoint - a single source both
# server/main.py (binding) and every connecting client (client_cli.py,
# play_online.py) read from, instead of each hand-rolling its own copy.
HOST = "localhost"
PORT = 8765

# The wire format's own color letters - public so a client building a
# command (client/client_cli.py, play_online.py) can get "W"/"B" for its
# own seat from the same single source of truth server/protocol.py's
# parse_command parses commands back out of, instead of each hand-rolling
# its own copy of this mapping.
COLOR_PREFIX = {WHITE: "W", BLACK: "B"}

# Wire message "type" values - the vocabulary server/ws_server.py,
# server/game_loop.py, and server/session.py send, and client/network_client.py,
# client/client_cli.py, client/network_message_adapter.py match against.
# Centralized so a typo on either side of the connection is a NameError at
# import time instead of a message that silently never matches anything at
# runtime.
LOGIN_ACK = "login_ack"
PLAY_ACK = "play_ack"
CREATE_ROOM_ACK = "create_room_ack"
JOIN_ROOM_ACK = "join_room_ack"
CANCEL_ROOM_ACK = "cancel_room_ack"
SEAT = "seat"
ACK = "ack"
ERROR = "error"
GAME_OVER = "game_over"
DISCONNECT_COUNTDOWN = "disconnect_countdown"
MATCHMAKING_TIMEOUT = "matchmaking_timeout"
MOVE_LOGGED = "move_logged"
CAPTURE = "capture"


# The two things a successful JOIN_ROOM can seat a connection as (see
# server/rooms.py's RoomRegistry.join: the first joiner past the creator
# becomes the opponent, everyone after that a spectator). A str subclass,
# not a plain Enum, for the same reason Color/ActionResultReason
# (model/piece.py) are: server/ws_server.py's `role == Role.OPPONENT`
# check, this dataclass's own JSON serialization, and
# client/setup_dialogs.py's `join_ack["role"] == Role.SPECTATOR` (the
# client only ever gets the plain decoded dict back, never this class
# itself) all keep comparing against the same "opponent"/"spectator" wire
# text either way.
class Role(str, Enum):
    OPPONENT = "opponent"
    SPECTATOR = "spectator"

    def __str__(self) -> str:
        return self.value
