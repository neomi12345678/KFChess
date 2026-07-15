# KFChess
⚡ KFChess | Mastering real-time chess, one move at a time.

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
  `realtime/real_time_arbiter.py`, `realtime/route_planner.py`,
  `input/controller.py`) types against `BoardRepresentation`, not `Board`.
  Only `boardio/board_parser.py` and `texttests/script_runner.py` name the
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

- **Movement shapes and timing.** `config.py` holds every direction/offset
  tuple (`ROOK_DIRECTIONS`, `KNIGHT_OFFSETS`, ...) and timing constant
  (`CELL_DURATION_MS`, `AIRBORNE_DURATION_MS`, `COOLDOWN_DURATION_MS`). Piece
  rules (`rules/piece_rules.py`) read these instead of hardcoding shapes, so
  a new piece kind is a config entry plus a small rule class.

- **Win/promotion conditions.** `rules/rule_engine.py` defines `WinCondition`
  and `PromotionRule` as `Protocol`s, injected into `GameEngine`/
  `RealTimeArbiter` with sane defaults (king-capture, last-rank-to-queen).
  Tests inject fakes (`NeverEndsWinCondition`, a no-op promotion rule) to
  prove a custom variant needs no changes to the engine itself.

- **Physics vs. real-time logic.** This is the hardest part of the
  assignment, split across two layers: `physics/motion.py` owns everything
  that depends on a piece's physical speed (`speed_m_per_sec`, read via
  `piece_config.py`) — it models each move as a `Trajectory` in continuous
  time, derives `move_cell_duration_ms`/`motion_duration_ms` from that
  speed, and computes the exact instant (`collision_time_ms`) two paths
  would occupy the same point. Nothing outside `physics/` ever reads
  `speed_m_per_sec` or a meters constant directly — `realtime/` and
  `engine/` only ever consume the millisecond durations physics hands back.
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
  whichever module happens to produce them first.

## Layout

```
model/      Domain types: Piece, Position, Board, shared game-state dataclasses
rules/      Move legality (piece shapes + board rules), win/promotion conditions
physics/    Speed/meters-derived durations and trajectory/collision math - the only layer that knows a piece has a physical speed
realtime/   Route/collision planning and the arbiter's state machine, built on physics/ durations - never reads speed_m_per_sec itself
engine/     GameEngine: ties rules + realtime together, exposes request_move/request_jump/wait/snapshot
boardio/    Text notation <-> Board (parser/printer)
input/      Pixel clicks -> board cells -> engine calls (Controller, BoardMapper)
view/       Renders a GameSnapshot onto an injected canvas (App wires click -> engine -> render)
texttests/  The .kfc script format: parsing + the shared command dispatcher
tests/      Unit tests per module, plus tests/integration/scripts/*.kfc end-to-end scenarios
```

`app.py`/`view/renderer.py` provide the interactive surface (click handling,
per-piece pixel interpolation while a piece is mid-flight) against any
canvas object that implements `draw_rect`/`draw_image`/`highlight_cell`/
`draw_text` — wiring in a real graphics backend (e.g. pygame) means
implementing that small interface, not touching engine/rules/realtime.
