"""Every client-side tunable constant in one place - typed command shorthand
for the terminal client and the timing knobs the networked GUI client uses.
These used to be defined one-per-module (client_cli.py, game_view_state.py,
network_client.py, play_online.py), each next to its own single use;
collected here instead so every client knob can be found and tuned from one
file.
"""

# client/client_cli.py - typed shorthand for the terminal client's Home
# screen actions (see _read_commands).
PLAY_INPUT = "play"
CREATE_ROOM_INPUT = "create room"
CANCEL_ROOM_INPUT = "cancel room"
JOIN_ROOM_PREFIX = "join room "

# client/game_view_state.py - how long a rejected move/jump's message stays
# on screen before StatusBannerState clears it.
ILLEGAL_MOVE_MESSAGE_S = 2.0

# client/network_client.py - a day-long stand-in for "wait indefinitely",
# passed as NetworkGameClient.wait_for_seat's own timeout by callers waiting
# on the room flow (a room has no server-side timeout of its own, unlike
# PLAY's matchmaking).
INDEFINITE_WAIT_S = 86_400.0

# client/network_client.py - how long NetworkGameClient's constructor waits
# for the background thread's websocket connection to come up before raising.
CONNECT_TIMEOUT_S = 5.0

# play_online.py - how often the networked GUI's render loop (and its
# pre-window wait for the first snapshot) yields to check for new server
# messages/redraw again.
RENDER_LOOP_POLL_S = 0.01
