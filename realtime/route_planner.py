import math
from dataclasses import dataclass
from typing import List, Optional

from config import CELL_DURATION_MS
from model.piece import Piece
from model.position import Position
from realtime.motion import Motion, Trajectory, collision_time_ms, is_straight_line, motion_duration_ms

# Tolerance, in ms, for treating a collision time as landing exactly on a
# cell boundary despite floating-point drift from the trajectory math.
_CELL_EPSILON_MS = 1e-6


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


@dataclass
class RoutePlan:
    # The cell this motion should actually travel to - the originally
    # requested destination, unless a same-color race truncates it short.
    destination: Position
    # True if this move must be rejected outright instead of starting it.
    is_blocked: bool


# The last cell along a straight path before destination - source itself
# for a knight-shaped jump, which has no such cell.
def cell_before(source: Position, destination: Position) -> Position:
    if not is_straight_line(source, destination):
        return source
    row_step = _sign(destination.row - source.row)
    col_step = _sign(destination.col - source.col)
    return Position(destination.row - row_step, destination.col - col_step)


# Whoever is already moving has right of way: a new move that would cross
# an opposing color's active path is rejected outright, and the active
# motion continues untouched to its own original destination - it captures
# normally on arrival if the piece that tried to cross it never moved. A
# same-color conflict isn't a rejection, just a race - the new mover stops
# one cell short instead of overwriting a teammate.
def plan_route(
    active_motions: List[Motion], piece: Piece, source: Position, destination: Position
) -> RoutePlan:
    if not is_straight_line(source, destination):
        return RoutePlan(destination=destination, is_blocked=False)

    requested = Trajectory(source, destination, motion_duration_ms(source, destination))

    earliest_collision_ms: Optional[float] = None
    blocking_motion: Optional[Motion] = None
    for motion in active_motions:
        if not is_straight_line(motion.source, motion.destination):
            continue
        in_flight = Trajectory(
            motion.source, motion.destination, motion.duration_ms, start_offset_ms=-motion.elapsed_ms
        )
        collision_ms = collision_time_ms(in_flight, requested)
        if collision_ms is None or collision_ms < 0:
            continue
        if earliest_collision_ms is None or collision_ms < earliest_collision_ms:
            earliest_collision_ms = collision_ms
            blocking_motion = motion

    if blocking_motion is None:
        return RoutePlan(destination=destination, is_blocked=False)

    if blocking_motion.piece.color != piece.color:
        return RoutePlan(destination=source, is_blocked=True)

    row_step = _sign(destination.row - source.row)
    col_step = _sign(destination.col - source.col)
    cells_reachable = math.floor(earliest_collision_ms / CELL_DURATION_MS + _CELL_EPSILON_MS)

    safe_cells = cells_reachable - 1
    if safe_cells < 1:
        return RoutePlan(destination=source, is_blocked=True)
    safe_cell = Position(source.row + row_step * safe_cells, source.col + col_step * safe_cells)
    return RoutePlan(destination=safe_cell, is_blocked=False)
