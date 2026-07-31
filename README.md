# KFChess
⚡ KFChess | Mastering real-time chess, one move at a time.

**Who this is for:** a chess player who wants the tension of live play —
reflexes and timing decide a close call, not just who happened to move
first — without giving up chess's own piece rules for something unrelated.
The payoff over ordinary turn-based chess: no waiting through an
opponent's turn, and every piece on the board is a live threat at once,
not just the ones it's currently "your turn" to worry about.

A chess variant where pieces move in continuous, real time instead of
turns: several pieces can be mid-flight at once, and the engine has to
resolve who gets where and when — including races between friendly pieces,
mid-flight interceptions, and jump-based defenses — instead of just
validating one move against a static board.

## Running it

```
python main.py < path/to/script.kfc
```

Input is a text script: a `Board:` section (rows of two-letter tokens like
`wR`/`bK`, or `.` for empty) followed by a `Commands:` section (`click x y`,
`jump x y` - pixel coordinates, converted to a board cell via `BoardMapper`
-, `wait ms`, `print board`). The same command dispatcher
(`texttests/script_runner.py`) backs both `main.py` and the integration
tests below, so there's exactly one implementation of "what a command
does," not two.

```
python -m pytest
```

runs the full suite (unit tests + the `.kfc` integration scripts).

### Playing it locally (graphical)

```
python play.py
```

Opens a real window (via `view/canvas/window.py`, backed by OpenCV) on the
standard chess starting position: click a piece then a destination to move
it, right-click (see `GameWindow`) to jump. This is the same `GameEngine`
`main.py` drives, just wired to a real canvas and a real click loop
(`app.py`'s `App`) instead of a `.kfc` script's `click`/`jump` commands.

### Playing it online

```
python -m server.main
```

starts the WebSocket server (`server/ws_server.py`) on `ws://localhost:8765`
(see `protocol/types.py`'s `HOST`/`PORT`) - a lobby that pairs players by
rating (`PLAY`) or lets one create/join an explicit room
(`CREATE_ROOM`/`JOIN_ROOM`), then ticks every active game's `GameEngine`
forward and broadcasts its snapshot to both seats.

```
python play_online.py
```

connects to that server: a small tkinter dialog (`client/setup_dialogs.py`)
handles login and matchmaking/room setup, then the same graphical window
`play.py` uses renders whatever the server broadcasts, with clicks sent as
wire commands instead of driving a local `GameEngine` directly. Run it
twice (two terminals/accounts) against the same server for a full two-player
game.

```
python -m client.client_cli
```

is a terminal-only alternative to `play_online.py` against the same server
and wire protocol: login, then `play`/`create room`/`join room <id>`/
`cancel room`, then fixed-width algebraic commands once seated (`e2e4` to
move, `jump e4` to jump - see `client/client_cli.py`'s `build_command`). No
`view/`/`input/` dependency at all, useful for scripting or a headless
second player.

Every server/service above speaks plaintext `ws://`/`http://` by default;
`SSL_CERT_FILE`/`SSL_KEY_FILE` (see `tls_config.py`) switch a given
process to `wss://`/`https://`, and either client's own `--tls`/
`--insecure-tls` flag opts into speaking it back (`--insecure-tls` for a
local self-signed dev cert, generated once via
`python -m tls_config <cert> <key>`) - see `.env.example`'s own worked
example.

## Architecture

The codebase is organized so each layer only knows about the layer below it
through an interface, not a concrete implementation — the goal (and the
thing this project is graded on) is that each of the following could be
swapped out without touching the others:

- **Storage.** `model/board.py` defines `BoardRepresentation`, a `Protocol`
  (width/height/is_in_bounds/get_piece/add_piece/remove_piece/move_piece), and
  `model/piece.py` defines the matching `PieceRepresentation` (id/color/kind/
  cell/state). `rules`, `engine`, and `realtime` all depend on these
  interfaces, never on `Board`'s dict-backed internals or `Piece`'s concrete
  dataclass layout — `tests/unit/test_board_representation.py` proves it by
  running the rule engine against a second, list-backed implementation.

  This is deliberately more than documentation: there are no `board._cells`
  reads outside `model/board.py`, and every module that touches a board
  (`rules/board_rules.py`, `rules/piece_rules.py`, `engine/game_engine.py`,
  `realtime/real_time_arbiter.py`, `realtime/route_planner.py`) types
  against `BoardRepresentation`, not `Board`. `input/controller.py` goes a
  step further and never touches a board at all - not even through
  `BoardRepresentation` - it only ever calls `GameEngine` (`can_select`/
  `piece_id_at`/`is_same_color`/`request_move`/`request_jump`), so board
  storage could change shape without this file changing either. Only
  `boardio/board_parser.py` and `texttests/script_runner.py` name the
  concrete class, because something has to build one from text.

  **What's still missing for a real binary/bitboard representation:** the
  Protocol split makes the storage swappable in principle, but several
  places currently mutate a `Piece` returned by `get_piece` in place instead
  of writing the change back through the board -
  `model/board.py` (`piece.cell = ...`), `realtime/real_time_arbiter.py`
  (`piece.state = ...`), and `rules/rule_engine.py`'s `LastRankPromotion`
  (`piece.kind = ...`). That's harmless for a dict-backed `Board`, where
  `get_piece` returns the same object stored in `_cells`, but it would
  silently do nothing on a packed/bit-based store, which can only
  synthesize a fresh `Piece` per call. Before a `BitboardRepresentation`
  lands, those three sites need to switch to an immutable `Piece`
  (`mark_moving()`/`mark_idle()`/`mark_captured()` returning a
  `dataclasses.replace`d copy) plus an explicit write-back call on the
  board - nothing in `rules/piece_rules.py` or `rules/board_rules.py` needs
  to change, since they only ever read piece attributes, never write them.
  Not done yet on purpose: there's no concrete storage to swap in today, so
  this is a plan, not a change made speculatively ahead of the need.

- **Notation.** `model/piece.py`'s `KIND_BY_LETTER`/`COLOR_BY_LETTER` are the
  single source of truth for board notation; `boardio/board_parser.py` and
  `boardio/board_printer.py` derive their valid-token sets from these tables
  instead of hardcoding a parallel list. `rules/rule_engine.py` also asserts
  at import time (`ensure_covers`) that every registered piece kind has a
  movement rule, so a kind added to `model/piece.py` without a matching rule
  fails immediately instead of becoming silently illegal-to-move.

- **Movement shapes and timing.** `logic_config.py` holds every direction/offset
  tuple (`ROOK_DIRECTIONS`, `KNIGHT_OFFSETS`, ...) and timing constant
  (`MOVE_CELL_DURATION_MS`, `AIRBORNE_BASE_DURATION_MS`,
  `SHORT_REST_BASE_DURATION_MS`, `LONG_REST_BASE_DURATION_MS`). Piece
  rules (`rules/piece_rules.py`) read the shape tuples instead of hardcoding
  directions/offsets, so a new piece kind is a config entry plus a small
  rule class.

- **Win/promotion conditions.** `rules/rule_engine.py` defines `WinCondition`
  and `PromotionRule` as `Protocol`s, injected into `GameEngine`/
  `RealTimeArbiter` with sane defaults (king-capture, last-rank-to-queen).
  Tests inject fakes (`NeverEndsWinCondition`, a no-op promotion rule) to
  prove a custom variant needs no changes to the engine itself.

- **Physics vs. real-time logic.** Split across two layers: `physics/motion.py`
  owns the continuous-time geometry — it models each move as a `Trajectory`,
  derives `motion_duration_ms` from how many cells it crosses, and computes
  the exact instant (`collision_time_ms`) two paths would occupy the same
  point. Every duration `physics/`/`realtime/` actually use is a flat,
  game-design millisecond constant read from `logic_config.py`
  (`MOVE_CELL_DURATION_MS`, `AIRBORNE_BASE_DURATION_MS`, ...) — never a
  physical unit or an asset-derived value. Piece animation assets
  (`assets/pieces/<code>/states/<state>/config.json`) still carry a
  `physics.speed_m_per_sec` field in their JSON, and `piece_config.py` (the
  view-side asset loader) parses that same file, but `load_animation` never
  reads that field back out and no realtime/physics module imports
  `piece_config.py` at all — see `logic_config.py`'s and `piece_config.py`'s
  own docstrings for why gameplay timing was deliberately cut loose from it.
  `realtime/route_planner.py` uses `collision_time_ms` *before* a motion
  starts — a move that would cross an opposing color's active path is
  rejected outright; a same-color race is truncated to the last safe cell
  short of the collision (falling back further still if a third piece
  already occupies that cell). `realtime/real_time_arbiter.py` resolves
  arrivals (including a reversed capture when a jumping piece defends its
  square) and applies a cooldown after landing from a jump. See
  `tests/unit/test_real_time_arbiter.py` for the edge cases this covers.

- **Shared vocabulary.** Event/snapshot types used across layers
  (`MoveResult`, `JumpResult`, `ArrivalEvent`, `PieceSnapshot`,
  `GameSnapshot`) live in `model/game_state.py` rather than being owned by
  whichever module happens to produce them first. `GameObserver` (also
  `model/game_state.py`) is the one interface `engine.GameEngine` notifies on
  every move/jump/arrival — `GameEngine` itself has no idea `events/` exists;
  see the next bullet.

- **Domain events.** `events/bus.py`'s `Bus` is a generic pub/sub keyed on
  `type(event)`, decoupling anything that reacts to the game (score-keeping,
  the move log, sound, animations, network broadcasting) from
  `GameEngine`'s own narrow `GameObserver` interface. `events/bus_bridge.py`'s
  `BusBridge` is the one `GameObserver` that translates
  `on_move_logged`/`on_arrival` calls into `Bus.publish` calls;
  `events/game_wiring.py`'s `wire_game_events` is the single place that
  answers "how do you hook a freshly built `GameEngine` up to this" - both a
  local game (`app_builder.py`) and a networked one (`server/session.py`)
  call it instead of duplicating the wiring. `events/observers.py`
  (move-log/score) and `events/sound.py`/`events/game_animations.py`
  (view-side cues) are `Bus` subscribers, not `GameEngine` observers
  themselves, so adding one is a new subscriber, never a change to `engine/`.

- **Wire protocol.** `protocol/` is the vocabulary shared by both sides of a
  network connection, and depends only on `model/` and `events/` — never on
  `client/`, `server/`, or `view/`. `protocol/types.py` centralizes the
  `MessageType`/`Role`/`Reason` string vocabulary; `protocol/lobby_messages.py`
  and `protocol/game_messages.py` are frozen dataclasses that self-register
  with `protocol/registry.py` (`message_to_dict`/`message_from_dict` are the
  one encode/decode path both directions of every connection use).
  `protocol/snapshot_codec.py` is the JSON codec for the one payload that
  isn't a registered message — the per-tick board+panel broadcast, which is
  the server's whole authoritative state as of that tick rather than a
  discrete event. `protocol/panel_state.py`'s `PanelState` is the
  client-side read model rebuilt from that broadcast each tick, standing in
  for `events/observers.py`'s `MoveLogObserver`/`ScoreObserver` (which only
  ever run server-side/locally, never having crossed the network themselves).

- **Internal event contracts.** `server/nats/events.py` is the deliberate
  counterpart to `protocol/` above, not a duplicate of it — kept as two
  separate modules on purpose, matching the two genuinely different
  problems each one solves. `protocol/` is the client↔server *wire*
  vocabulary: many message types share one long-lived connection, so
  `protocol/registry.py` dispatches each incoming message at runtime by its
  own `MessageType` tag. The NATS control-plane events between `services/*`
  (`matchmaking.requested`, `match.found`, `room.opponent_joined`,
  `game.allocated`, `game.created`, `game.finished`, ...) don't share that
  problem — a NATS subject is subscribed to individually, so the subject
  string itself already disambiguates payload shape, and a second runtime
  dispatch layer on top would be pure overhead. `server/nats/events.py` is
  one plain `@dataclass` per subject instead, each carrying its own
  `SUBJECT` plus `encode()`/`decode()`. Every publisher
  (`services/api_gateway/main.py`, `services/matchmaker/main.py`,
  `services/game_allocator/main.py`, `services/ws_gateway/main.py`,
  `server/game_loop.py`, `server/nats/lifecycle.py`) and the one batching
  consumer (`services/persistence_worker/main.py`) builds/reads these
  instead of a raw dict keyed by convention — a typo in a field name is now
  a `NameError`/`AttributeError` at the call site, not a silent `KeyError`
  three services away.

- **Server.** `server/` hosts the authoritative game. `server/session.py`'s
  `GameSession` wraps one `engine.GameEngine` (built the same way local play
  builds one, via `engine/game_builder.py`) plus the one check `GameEngine`
  itself has no notion of — which connection is allowed to move which color
  (`GameEngine.request_move`/`request_jump` take no color argument at all,
  since this is a real-time game with no turn order to enforce it through).
  `server/game_loop.py`'s `GameLoop` owns every concurrently active session
  plus the matchmaking queue, and the single tick that advances all of them.
  `server/router.py`'s `CommandRouter` makes routing *decisions* (is this
  `PLAY` allowed right now, does this `JOIN_ROOM` seat an opponent or a
  spectator) against plain typed values, and is never async and never
  touches a websocket/JSON/dict itself; `server/ws_server.py`'s `GameServer`
  is the only async, wire-facing piece, decoding through
  `protocol.registry.decode_json_message` and sending through
  `server/connections.py`'s `ConnectionRegistry` (the only place that ever
  calls `websocket.send`). `server/accounts.py`/`server/accounts_db.py`
  (login) and `server/rating_store.py`/`server/rating.py` (ELO) are
  deliberately separate concerns that happen to share one SQLite table.
  **`server/` never imports `client/` or `view/`** — its own dependencies
  stop at `model/`, `rules/`, `physics/`, `realtime/`, `engine/`, `events/`,
  and `protocol/`.

- **Client.** `client/` is the networked counterpart to `input/`/`view/`, and
  is just as strictly isolated: **it never imports `server/`**, only
  `protocol/` (the same wire vocabulary the server speaks), `events/` (its
  own local `Bus`, for sound/animation cues), `model/` (`GameSnapshot`,
  rebuilt from the wire by `protocol/snapshot_codec.py`, never read off a
  live `Board`), and a couple of leaf utility modules with no server/view
  dependencies of their own (`boardio/algebraic_notation.py` for
  `client/client_cli.py`'s typed move input, `tls_config.py` for opt-in
  TLS). `client/network_client.py`'s `NetworkGameClient` runs the
  actual asyncio/websocket connection on a background thread, so
  `view/canvas/window.py`'s blocking, synchronous frame loop never has to be
  async itself. `client/network_message_adapter.py` and
  `client/game_view_state.py` are the client-side mirrors of
  `events/bus_bridge.py` and `events/observers.py` — translating typed wire
  messages into `Bus` events instead of live `GameEngine` calls, since
  there's no local `Board` to query. `client/network_controller.py` is
  `input/controller.py`'s networked counterpart, working off the
  last-received `GameSnapshot` instead of a live engine (legality is still
  entirely the server's call). Two entry points sit on top of this package:
  `play_online.py` (the GUI, sharing `view/` with local play) and
  `client/client_cli.py` (a terminal client speaking the same wire protocol,
  with no `view/`/`input/` dependency at all).

## Layout

```
model/      Domain types: Piece, Position, Board, shared game-state dataclasses
rules/      Move legality (piece shapes + board rules), win/promotion conditions
physics/    Trajectory/collision-time math, in flat millisecond durations (logic_config.py) - never a physical unit
realtime/   Route/collision planning and the arbiter's state machine, built on physics/ durations
engine/     GameEngine: ties rules + realtime together, exposes request_move/request_jump/wait/snapshot
boardio/    Text notation <-> Board (parser/printer)
input/      Pixel clicks -> board cells -> engine calls (Controller, BoardMapper) - local play only
view/       Renders a GameSnapshot onto an injected canvas (App wires click -> engine -> render)
events/     Generic pub/sub Bus + GameEngine-observer bridges; move-log/score/sound/animation subscribers
protocol/   Wire vocabulary shared by client/ and server/: message dataclasses, JSON codec, registry
server/     Authoritative networked game: lobby, matchmaking/rooms, GameSession/GameLoop, accounts/rating
client/     Networked counterpart to input/+view/: NetworkGameClient, GameViewState, NetworkController
texttests/  The .kfc script format: parsing + the shared command dispatcher
tests/      Unit tests per module, plus tests/integration/scripts/*.kfc end-to-end scenarios
```

Everything above is a package; a handful of top-level modules are shared
config or composition roots instead of a layer of their own, and are read
accordingly:

- `logic_config.py`/`display_config.py` split gameplay-timing/movement-shape
  constants from pixel/panel sizing constants (see the "Physics vs.
  real-time logic" bullet above) — `rules/physics/realtime/engine/boardio`
  import only the former, `input/view` only the latter.
- `piece_config.py` is the view-side asset loader (sprite animation config);
  no logic-layer module imports it.
- `frame_clock.py`'s `FrameClock` is a plain elapsed-time helper shared
  between `play.py`'s local frame loop and `server/game_loop.py`'s tick loop.
- `main.py`, `play.py`/`app.py`/`app_builder.py`, `play_online.py`, and
  `server/main.py`/`client/client_cli.py` are the composition roots — the
  only places allowed to import across every layer at once to wire a
  runnable program together. No package under `model/` through `client/`
  above imports any of them.

`app.py`/`view/renderer.py` provide the interactive surface (click handling,
per-piece pixel interpolation while a piece is mid-flight) against any
canvas object that implements `draw_rect`/`draw_image`/`highlight_cell`/
`draw_text` — wiring in a real graphics backend (e.g. pygame) means
implementing that small interface, not touching engine/rules/realtime.
