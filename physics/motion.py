from dataclasses import dataclass
from typing import Optional

import piece_config
from config import METERS_PER_SQUARE
from model.piece import PieceRepresentation
from model.position import Position

_EPSILON = 1e-9


# Anything that isn't a straight rank/file/diagonal line is treated as a
# jump (a knight's L-shape) - it has no continuous path to collide along,
# matching how knights already ignore what's in between.
def is_straight_line(source: Position, destination: Position) -> bool:
    row_diff = destination.row - source.row
    col_diff = destination.col - source.col
    return row_diff == 0 or col_diff == 0 or abs(row_diff) == abs(col_diff)


# How long this piece takes to cross one square while moving, derived from
# its own "move" state's physics.speed_m_per_sec (assets/pieces/<code>/
# states/move/config.json) - every piece kind currently shares the same
# speed, but this reads each piece's own data rather than assuming that.
def move_cell_duration_ms(piece: PieceRepresentation) -> int:
    code = piece_config.piece_code(piece.kind, piece.color)
    speed = piece_config.load(code, "move").speed_m_per_sec
    return round(1000 * METERS_PER_SQUARE / speed)


def motion_duration_ms(source: Position, destination: Position, piece: PieceRepresentation) -> int:
    cells = max(abs(destination.row - source.row), abs(destination.col - source.col))
    return cells * move_cell_duration_ms(piece)


# A piece currently traveling from source to destination.
@dataclass
class Motion:
    piece: PieceRepresentation
    source: Position
    destination: Position
    elapsed_ms: int = 0

    @property
    def duration_ms(self) -> int:
        return motion_duration_ms(self.source, self.destination, self.piece)

    def is_complete(self) -> bool:
        return self.elapsed_ms >= self.duration_ms


# A timed, out-of-band period tracked for a piece - airborne after a jump,
# short_rest after landing from one, or long_rest after an ordinary move -
# before it's automatically cleared (see RealTimeArbiter.is_airborne()/
# is_in_cooldown()). duration_ms is a fixed game-design constant
# (config.py), resolved once when the period starts - never derived from
# the piece's own animation config.
@dataclass
class TimedState:
    piece: PieceRepresentation
    duration_ms: int
    elapsed_ms: int = 0

    def is_expired(self) -> bool:
        return self.elapsed_ms >= self.duration_ms


# A straight-line path through continuous space and time: at `source` when
# `start_offset_ms` elapses (relative to "now"), at `destination` when
# `start_offset_ms + duration_ms` elapses. A motion already in flight has
# a negative start_offset_ms (it started in the past); a newly requested
# move starts at offset 0.
@dataclass(frozen=True)
class Trajectory:
    source: Position
    destination: Position
    duration_ms: int
    start_offset_ms: int = 0

    @property
    def end_offset_ms(self) -> int:
        return self.start_offset_ms + self.duration_ms


# The instant, in the shared "now"-relative ms coordinate, at which two
# straight-line trajectories occupy the same point - None if they never do.
def collision_time_ms(a: Trajectory, b: Trajectory) -> Optional[float]:
    if a.duration_ms == 0 or b.duration_ms == 0:
        return None

    overlap_start = max(a.start_offset_ms, b.start_offset_ms)
    overlap_end = min(a.end_offset_ms, b.end_offset_ms)
    if overlap_start > overlap_end:
        return None

    row_rate_a = (a.destination.row - a.source.row) / a.duration_ms
    col_rate_a = (a.destination.col - a.source.col) / a.duration_ms
    row_rate_b = (b.destination.row - b.source.row) / b.duration_ms
    col_rate_b = (b.destination.col - b.source.col) / b.duration_ms

    # Equating position_a(t) == position_b(t) per axis reduces to a linear
    # equation coeff * t == offset; a shared collision time must satisfy
    # both the row and the column equation at once.
    row_coeff = row_rate_a - row_rate_b
    row_offset = (b.source.row - a.source.row) + row_rate_a * a.start_offset_ms - row_rate_b * b.start_offset_ms
    col_coeff = col_rate_a - col_rate_b
    col_offset = (b.source.col - a.source.col) + col_rate_a * a.start_offset_ms - col_rate_b * b.start_offset_ms

    collision_time = None
    if abs(row_coeff) > _EPSILON:
        candidate = row_offset / row_coeff
        if abs(col_coeff) > _EPSILON:
            if abs(col_coeff * candidate - col_offset) < _EPSILON:
                collision_time = candidate
        elif abs(col_offset) < _EPSILON:
            collision_time = candidate
    elif abs(row_offset) < _EPSILON:
        if abs(col_coeff) > _EPSILON:
            collision_time = col_offset / col_coeff
        elif abs(col_offset) < _EPSILON:
            collision_time = overlap_start

    if collision_time is None or not (overlap_start - _EPSILON <= collision_time <= overlap_end + _EPSILON):
        return None

    return collision_time


# True if two straight-line trajectories would occupy the same point at
# the same instant, somewhere within the time window both are in flight.
def trajectories_collide(a: Trajectory, b: Trajectory) -> bool:
    return collision_time_ms(a, b) is not None
