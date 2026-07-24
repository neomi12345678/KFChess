"""Wire-level constants shared by both sides of the network connection: the
server endpoint address, the message "type" tag vocabulary every message in
either direction carries (see lobby_messages.py/game_messages.py), and Role,
the two things a successful JOIN_ROOM can seat a connection as.
"""

from enum import Enum

# The real, well-known server endpoint - a single source both
# server/main.py (binding) and every connecting client (client_cli.py,
# play_online.py) read from, instead of each hand-rolling its own copy.
HOST = "localhost"
PORT = 8765

# Wire message "type" values - the vocabulary every message in either
# direction carries (see protocol/registry.py's register()/message_to_dict):
# client->server (LOGIN/PLAY/.../MOVE/JUMP, see lobby_messages.py/
# game_messages.py's request dataclasses) and server->client (the *_ACK/
# SEAT/... dataclasses in the same two modules) alike. Centralized so a typo
# on either side of the connection is a NameError at import time instead of a
# message that silently never matches anything at runtime. A str subclass,
# not a plain module-level constant, for the same reason Role is: registry.py
# stores/looks these up as plain dict keys against a wire payload's own
# plain-str "type" field, and every dataclass's own `type: str = ...` default
# still compares/serializes identically either way.
class MessageType(str, Enum):
    LOGIN = "login"
    PLAY = "play"
    CREATE_ROOM = "create_room"
    CANCEL_ROOM = "cancel_room"
    JOIN_ROOM = "join_room"
    MOVE = "move"
    JUMP = "jump"

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

    def __str__(self) -> str:
        return self.value


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


# The wire-ready "reason" text every rejecting/informational ack carries
# (LoginAckMessage/PlayAckMessage/CreateRoomAckMessage/JoinRoomAckMessage/
# CancelRoomAckMessage/AckMessage's own "reason" field, and server/rooms.py's
# RoomError, whose str(error) *is* one of these - see its own docstring) -
# centralized for the same reason MessageType is (a typo here would
# otherwise be a string that silently never matches anything, not a
# NameError at import time). No caller branches on a specific member today
# (every existing consumer just displays "reason" as free text - see
# client/setup_dialogs.py) - this exists so that when one eventually does,
# it has a fixed vocabulary to match against instead of a scattered set of
# string literals across server/router.py, server/ws_server.py, and
# server/rooms.py to first go hunt down.
class Reason(str, Enum):
    QUEUED = "queued"
    NOT_IN_GAME = "not_in_game"
    WRONG_SEAT = "wrong_seat"
    WRONG_PASSWORD = "wrong_password"
    ALREADY_IN_GAME = "already_in_game"
    ALREADY_QUEUED = "already_queued"
    ALREADY_IN_A_ROOM = "already_in_a_room"
    ROOM_NOT_FOUND = "room_not_found"
    NOT_IN_A_ROOM = "not_in_a_room"
    NOT_THE_CREATOR = "not_the_creator"
    ALREADY_STARTED = "already_started"

    def __str__(self) -> str:
        return self.value
