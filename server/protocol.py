"""Server-only half of the wire protocol: parsing text commands in
("We2e4"/"WJe4"/"LOGIN ..."/"PLAY"/room commands). The JSON snapshot/panel
encoding both sides share, plus the server endpoint and color-letter
mapping, live in net_protocol.py instead - a client (client/client_cli.py,
client/game_view_state.py, play_online.py) only ever needs that half, never
the command-parsing grammar below, so it imports net_protocol directly
rather than reaching into this package.

Kept fully isolated from boardio/ - this is a network-facing vocabulary
(uppercase "W"/"B" color letters, no piece letter, a bare "J" jump marker)
distinct from boardio's own board-notation/algebraic-notation letters, so it
has no business living alongside those.

Command grammar:
    "<W|B><source><dest>"   e.g. "We2e4" - move
    "<W|B>J<square>"        e.g. "WJe4"  - jump (in place, no destination)
    "LOGIN <username> <password>"  e.g. "LOGIN alice secret123" - the
                            connection's login step (see
                            server/ws_server.py and server/accounts.py),
                            space-delimited rather than this file's compact
                            move/jump grammar since a username/password are
                            free text, not fixed-width squares.
    "PLAY"                  requests matchmaking (see server/matchmaking.py)
                            - no arguments, since the connection's own
                            identity/rating are already known from LOGIN.
    "CREATE_ROOM"            opens a new room (see server/rooms.py) - no
                            arguments; the room's id comes back in the ack,
                            not chosen by the caller.
    "JOIN_ROOM <id>"        joins an existing room by id - the first joiner
                            becomes the opponent, every joiner after that a
                            spectator (see server/rooms.py's RoomRegistry).
    "CANCEL_ROOM"           withdraws the caller's own still-pending
                            (no opponent yet) room - no arguments, since
                            a connection is only ever the creator of at
                            most one room at a time.
where <square> is a file letter ("a".."h"-range, board-width-dependent) plus
a rank number, the same square-name shape as boardio.algebraic_notation's
square_name, just inverted.
"""

from dataclasses import dataclass
from typing import Optional

from model.position import Position
from net_protocol import COLOR_PREFIX

_COLOR_BY_PREFIX = {letter: color for color, letter in COLOR_PREFIX.items()}
_LOGIN_PREFIX = "LOGIN "
PLAY_COMMAND = "PLAY"

MOVE = "move"
JUMP = "jump"


class ProtocolError(Exception):
    """A command string that doesn't match the grammar at all, or names a
    square outside the board - never raised for a legal-looking command
    that GameEngine itself goes on to reject (route conflict, cooldown,
    wrong color, ...); those are reported back as an ordinary rejection,
    not a protocol failure."""


@dataclass(frozen=True)
class Command:
    color: str
    kind: str
    source: Position
    destination: Optional[Position]


# The inverse of boardio.algebraic_notation.square_name: file letter -> col,
# rank number -> row, using the same board_height-relative convention (row 0
# is rank board_height, matching white's pawns advancing toward row 0).
def parse_square(square: str, board_height: int) -> Position:
    if len(square) < 2 or not square[0].isalpha() or not square[1:].isdigit():
        raise ProtocolError(f"malformed square: '{square}'")

    col = ord(square[0].lower()) - ord("a")
    rank_number = int(square[1:])
    row = board_height - rank_number

    if col < 0:
        raise ProtocolError(f"malformed square: '{square}'")

    return Position(row, col)


def parse_command(text: str, board_height: int) -> Command:
    if len(text) < 2 or text[0] not in _COLOR_BY_PREFIX:
        raise ProtocolError(f"malformed command: '{text}'")

    color = _COLOR_BY_PREFIX[text[0]]
    rest = text[1:]

    if rest[0] == "J":
        return Command(color=color, kind=JUMP, source=parse_square(rest[1:], board_height), destination=None)

    # A move's source/dest are both fixed-width squares (one file letter,
    # then digits) with no separator, so the split point is wherever the
    # rank digits of the first square end and the second square's file
    # letter begins.
    split = 1
    while split < len(rest) and rest[split].isdigit():
        split += 1
    if split >= len(rest):
        raise ProtocolError(f"malformed command: '{text}'")

    source = parse_square(rest[:split], board_height)
    destination = parse_square(rest[split:], board_height)
    return Command(color=color, kind=MOVE, source=source, destination=destination)


@dataclass(frozen=True)
class LoginRequest:
    username: str
    password: str


# Returns the (username, password) for a "LOGIN <username> <password>"
# message, or None for any other text - lets a caller (server/ws_server.py)
# check "was this a login message at all?" without first needing to know it
# wasn't a move/jump. Still raises ProtocolError for a recognized-but-
# malformed login (missing username or password), the same way
# parse_command raises for a recognized-but-malformed move/jump, rather than
# silently treating it as "not a login message". The password itself is
# whatever text follows the username, spaces included - only the boundary
# between username and password is split on the first run of whitespace.
def parse_login(text: str) -> Optional[LoginRequest]:
    if not text.startswith(_LOGIN_PREFIX):
        return None

    rest = text[len(_LOGIN_PREFIX):].strip()
    parts = rest.split(None, 1)
    if len(parts) != 2 or not parts[1].strip():
        raise ProtocolError("LOGIN requires a username and a password")

    return LoginRequest(username=parts[0], password=parts[1].strip())


def is_play_command(text: str) -> bool:
    return text.strip() == PLAY_COMMAND


CREATE_ROOM_COMMAND = "CREATE_ROOM"
CANCEL_ROOM_COMMAND = "CANCEL_ROOM"
_JOIN_ROOM_PREFIX = "JOIN_ROOM "


def is_create_room_command(text: str) -> bool:
    return text.strip() == CREATE_ROOM_COMMAND


def is_cancel_room_command(text: str) -> bool:
    return text.strip() == CANCEL_ROOM_COMMAND


# Returns the room id for a "JOIN_ROOM <id>" message, or None for any other
# text - the same "was this one of my message shapes at all" role
# parse_login plays for LOGIN. Still raises ProtocolError for a
# recognized-but-empty id, rather than silently treating it as "not a
# JOIN_ROOM message".
def parse_join_room(text: str) -> Optional[str]:
    if not text.startswith(_JOIN_ROOM_PREFIX):
        return None

    room_id = text[len(_JOIN_ROOM_PREFIX):].strip()
    if not room_id:
        raise ProtocolError("JOIN_ROOM requires a room id")

    return room_id
