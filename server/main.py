"""Entry point: python -m server.main"""

import asyncio
import os

from boardio.board_parser import parse as parse_board
from net_protocol import HOST, PORT
from server.accounts import AccountStore
from server.rooms import RoomStore
from server.ws_server import GameServer

# Alongside this file, not CWD-relative - a real, persistent file (unlike
# tests, which each get their own ":memory:" AccountStore/RoomStore - see
# server/accounts.py's and server/rooms.py's own db_path docstrings).
DB_PATH = os.path.join(os.path.dirname(__file__), "accounts.db")
ROOM_DB_PATH = os.path.join(os.path.dirname(__file__), "rooms.db")

STARTING_BOARD = """
bR bN bB bQ bK bB bN bR
bP bP bP bP bP bP bP bP
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
wP wP wP wP wP wP wP wP
wR wN wB wQ wK wB wN wR
""".strip()

# Called fresh for every matched pair (see server/ws_server.py's
# board_factory) - a new game needs its own Board/pieces, not one reused
# (and thus stale with the previous game's captures) across games.
def _new_board():
    return parse_board(STARTING_BOARD)


async def _main() -> None:
    account_store = AccountStore(DB_PATH)
    room_store = RoomStore(ROOM_DB_PATH)
    server = GameServer(_new_board, account_store, host=HOST, port=PORT, room_store=room_store)
    print(f"KFChess server listening on ws://{HOST}:{PORT}")
    await server.run_forever()


def main() -> None:  # pragma: no cover
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
