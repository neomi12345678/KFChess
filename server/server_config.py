"""Every server-side tunable constant in one place - tick rate, matchmaking/
disconnect timing, room-id shape, ELO's K-factor, websocket keepalive, and
password hashing. These used to be defined one-per-module (game_loop.py,
matchmaking.py, rooms.py, rating.py, ws_server.py, accounts.py, session.py),
each next to its own single use; collected here instead so every server knob
can be found and tuned from one file. The owning module still imports its
own constant back as its parameter default, so call sites needing a default
don't have to reach into this module themselves.
"""

# server/game_loop.py - GameLoop.run_forever's own tick period. Mirrors
# play.py's frame loop (real elapsed wall-clock time, fractional ms carried
# into the next tick rather than truncated away) so every networked game's
# simulated clock keeps the same feel as local play.
DEFAULT_TICK_INTERVAL_S = 0.05

# server/matchmaking.py - MatchmakingQueue's own pairing/timeout knobs.
RATING_RANGE = 100
MATCHMAKING_TIMEOUT_MS = 60_000

# server/rooms.py - length of a freshly generated room id (RoomRegistry._new_id).
ROOM_ID_LENGTH = 6

# server/rating.py - standard chess ELO's own conventional step size, how
# much of the gap between expected and actual outcome one game moves a rating.
RATING_K_FACTOR = 32

# server/ws_server.py - tighter than `websockets`' own 20s/20s stock
# defaults (a dead connection must be caught well inside session.py's
# DISCONNECT_GRACE_MS below), but deliberately not razor-thin - see that
# module's own docstring for why PING_TIMEOUT_S stays comfortably above the
# tightest number that merely happens to survive today's observations.
PING_INTERVAL_S = 10.0
PING_TIMEOUT_S = 10.0
CLOSE_TIMEOUT_S = 5.0

# server/accounts.py - a first-ever LOGIN registers its username at this
# rating; PBKDF2-SHA256 with a random per-account salt is the hashing scheme.
STARTING_RATING = 1200
PASSWORD_HASH_NAME = "sha256"
PASSWORD_HASH_ITERATIONS = 200_000

# server/session.py - how long a disconnected seat gets before it's ruled a
# resignation (the Home-screen slide's own "auto-resign after 20 sec").
DISCONNECT_GRACE_MS = 20_000
