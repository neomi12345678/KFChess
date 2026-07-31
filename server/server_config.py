"""Every server-side tunable constant in one place - tick rate, matchmaking/
disconnect timing, room-id shape, ELO's K-factor, websocket keepalive, and
password hashing. These used to be defined one-per-module (game_loop.py,
matchmaking.py, rooms.py, rating.py, ws_server.py, accounts.py, session.py),
each next to its own single use; collected here instead so every server knob
can be found and tuned from one file. The owning module still imports its
own constant back as its parameter default, so call sites needing a default
don't have to reach into this module themselves.

The four matchmaking knobs below also read a KFCHESS_-prefixed env var, so
an operator can retune pairing behavior per-deployment (a looser rating
range during a low-traffic period, a shorter timeout for a demo) without a
code change - the same tunability a competing implementation's scattered
per-service os.getenv() calls had, but without giving that up as the single
place every server knob is defined and found: the default a deployment gets
when nothing overrides it is still spelled out here, in one file, not
rediscovered by grepping five services.
"""

import os

# server/game_loop.py - GameLoop.run_forever's own tick period. Mirrors
# play.py's frame loop (real elapsed wall-clock time, fractional ms carried
# into the next tick rather than truncated away) so every networked game's
# simulated clock keeps the same feel as local play.
DEFAULT_TICK_INTERVAL_S = 0.05

# server/matchmaking.py - MatchmakingQueue's own pairing/timeout knobs.
RATING_RANGE = int(os.getenv("KFCHESS_RATING_RANGE", "100"))
MATCHMAKING_TIMEOUT_MS = int(os.getenv("KFCHESS_MATCHMAKING_TIMEOUT_MS", "60000"))

# server/matchmaking.py - how often a still-waiting PLAY queue entry gets a
# reassuring "still searching" push (MatchmakingStatusMessage) between
# enqueue and either a match or MATCHMAKING_TIMEOUT_MS above.
MATCHMAKING_STATUS_INTERVAL_MS = int(os.getenv("KFCHESS_MATCHMAKING_STATUS_INTERVAL_MS", "5000"))

# server/rooms.py - length of a freshly generated room id (RoomRegistry._new_id).
ROOM_ID_LENGTH = 6

# server/rating.py - standard chess ELO's own conventional step size, how
# much of the gap between expected and actual outcome one game moves a rating.
RATING_K_FACTOR = int(os.getenv("KFCHESS_RATING_K_FACTOR", "32"))

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

# server/accounts.py's issue_session_token/verify_session_token - how long a
# session token stays valid after LOGIN/POST-login issues it. Sized for
# realistic lobby dwell time (a human sitting at client/setup_dialogs.py's
# setup screen between logging in and actually starting a game), not for the
# IDENTIFY handshake itself (sub-second) or DISCONNECT_GRACE_MS below (both
# far shorter than the real constraint). No logout/revocation exists
# anywhere in this codebase today, so this TTL is the only expiry a stolen
# token ever gets - a deliberate, documented trade-off, not an oversight.
SESSION_TOKEN_TTL_S = 3600 * 6

# server/session.py - how long a disconnected seat gets before it's ruled a
# resignation (the Home-screen slide's own "auto-resign after 20 sec").
DISCONNECT_GRACE_MS = 20_000

# server/game_loop.py - how often GameLoop persists Server_Design.md §9's
# own "lightweight fairness checkpoint" (score, elapsed time, remaining
# pieces) to Redis per active game - not exact mid-flight animation state,
# just enough for a fair void decision if the shard crashes before the game
# ends normally. "Every few seconds" per the design doc, not a physical
# unit - same flat-ms-constant convention as MATCHMAKING_STATUS_INTERVAL_MS
# above.
FAIRNESS_CHECKPOINT_INTERVAL_MS = 5_000

# services/game_allocator/main.py - how often the recovery sweep checks
# every room it's holding a shard assignment for (server/redis/room_shard_index.py's
# RoomShardIndex) against server/redis/shard_registry.py's ShardRegistry
# of currently-live shards, voiding any room whose shard has gone quiet.
# Well under ShardRegistry's own default 10s TTL so a dead shard's rooms
# get caught within one sweep of the lease actually expiring, without
# polling Redis needlessly often.
SHARD_RECOVERY_SWEEP_INTERVAL_MS = 5_000

# server/redis/room_shard_index.py - Server_Design.md §4's own room
# ownership lease ("SET room:450:owner worker-B NX PX 5000, renewed by
# heartbeat while the worker holds the room"). ROOM_LEASE_TTL_MS is that
# PX; ROOM_LEASE_RENEW_INTERVAL_MS (server/game_loop.py's own
# _advance_game, same cadence convention as FAIRNESS_CHECKPOINT_INTERVAL_MS
# above) is well under it - the same 3x-or-more TTL/renewal-interval ratio
# server/redis/shard_registry.py's own 3s-heartbeat/10s-TTL already uses,
# so a handful of missed renewals (a slow tick, a brief Redis blip) never
# expire a still-live room's own lease.
ROOM_LEASE_TTL_MS = 15_000
ROOM_LEASE_RENEW_INTERVAL_MS = 5_000

# services/game_allocator/main.py - Server_Design.md §9's own "bound the
# blast radius: cap each Game-Authority pod's concurrent room count... so
# one crash affects a small, known slice of the total games, not
# everyone." §10's own planning number (~500 concurrent rooms/shard,
# "a planning assumption pending real benchmarking," not yet a measured
# one) - kept as that same document's own number rather than invented here,
# see server/redis/shard_registry.py's own pick_shard docstring for how
# this is actually enforced (each shard reports its own live room count on
# every heartbeat; the allocator filters out anything at or over this before
# picking).
MAX_ROOMS_PER_SHARD = 500

# server/main.py - Server_Design.md §8's own "a Game-Authority pod being
# retired stops accepting new rooms, drains its existing ones (bounded
# <=90s wait), then exits." The upper bound on how long a SIGTERM'd shard
# waits for its own currently-active games to finish naturally before
# giving up and exiting anyway (see server/main.py's own _main, which
# stops this shard from being picked for anything *new* the instant the
# signal arrives - see MAX_ROOMS_PER_SHARD above and
# server/redis/shard_registry.py's own pick_shard).
SHARD_DRAIN_TIMEOUT_MS = 90_000

# server/redis/matchmaker_leader.py - only the standalone Matchmaker
# replica holding this lease actually ticks the shared RedisMatchmakingQueue
# (see that module's own docstring on why concurrent tickers would
# double-count waited_ms and double-claim a match) - renewed every tick
# (services/matchmaker/main.py's own MATCHMAKER_TICK_INTERVAL_S, 50ms by
# default), so this TTL only bounds how long a crashed leader's own lease
# lingers before a live replica notices and takes over - the same
# well-under-the-renew-cadence margin ROOM_LEASE_TTL_MS/
# ROOM_LEASE_RENEW_INTERVAL_MS above already uses, just shorter throughout
# since a missed matchmaking tick is far cheaper to fail over quickly than
# a live room's own lease.
MATCHMAKER_LEADER_TTL_MS = 2_000

# services/persistence_worker/main.py - Server_Design.md §8's own
# "Persistence Workers consume it in batches" - a flush happens once
# PERSISTENCE_BATCH_SIZE game.finished events have queued up, or once
# PERSISTENCE_BATCH_FLUSH_INTERVAL_MS has passed since the oldest
# unflushed one arrived, whichever comes first (see that module's own
# _run_batch_flusher) - so a quiet period still flushes promptly instead
# of leaving a small batch waiting indefinitely for it to fill.
PERSISTENCE_BATCH_SIZE = 50
PERSISTENCE_BATCH_FLUSH_INTERVAL_MS = 2_000
