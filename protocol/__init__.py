"""Wire vocabulary shared by *both* sides of the network connection - lives
at the top level, outside server/, because a client has no business
importing the server package just to talk the server's own wire format.
Split by concern rather than one flat module:

    types.py            HOST/PORT, the color-letter mapping, message "type"
                        tags, and Role.
    registry.py         type-tag -> message-class lookup, populated by
                        lobby_messages.py/game_messages.py at import time.
    lobby_messages.py   login/matchmaking/room commands and their acks.
    game_messages.py    move/jump commands and in-game server->client
                        messages (acks, captures, disconnects, game-over).
    snapshot_codec.py   the per-tick board+panel broadcast codec.
    panel_state.py      the client-side read model rebuilt from it.

server/protocol.py builds its server-only half (text command grammar:
parsing "We2e4"/"LOGIN ..."/"PLAY"/room commands) on top of this package -
nothing in server/protocol.py duplicates what's here, it only imports
COLOR_PREFIX back for its own parsing.
"""
