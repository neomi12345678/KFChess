"""Wire vocabulary shared by *both* sides of the network connection - lives
at the top level, outside server/, because a client has no business
importing the server package just to talk the server's own wire format.
Split by concern rather than one flat module:

    types.py            HOST/PORT, message "type" tags, and Role.
    registry.py         type-tag -> message-class lookup (register()) plus
                        the encode/decode functions every message in either
                        direction goes through, populated by
                        lobby_messages.py/game_messages.py at import time.
    lobby_messages.py   login/matchmaking/room commands and their acks.
    game_messages.py    move/jump commands and in-game server->client
                        messages (acks, captures, disconnects, game-over).
    snapshot_codec.py   the per-tick board+panel broadcast codec.
    panel_state.py      the client-side read model rebuilt from it.

Every message in either direction is one of this package's own registered
dataclasses, decoded through the same registry.message_from_dict regardless
of which side sent it - server/ws_server.py reaches that through
registry.decode_json_message directly; client/network_client.py calls
message_from_dict itself instead, since it needs the parsed payload dict a
step earlier than decode_json_message would give it (see registry.py's own
docstring on decode_json_message for why). See
server/command_translation.py's own docstring for the one place server-side
that still turns a decoded MoveMessage/JumpMessage into the engine-facing
Command shape.
"""
