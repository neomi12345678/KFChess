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
    # requested destination, unless a collision truncates it short.
    destination: Position
    # Set if the truncation lands exactly on an opposing piece: that piece
    # must be captured the instant this motion arrives at `destination`.
    capture_target: Optional[Piece]
    # True if there's no cell this piece can safely reach at all - reject
    # the move outright instead of starting it.
    is_blocked: bool


# The last cell along a straight path before destination - source itself
# for a knight-shaped jump, which has no such cell.
def cell_before(source: Position, destination: Position) -> Position:
    if not is_straight_line(source, destination):
        return source
    row_step = _sign(destination.row - source.row)
    col_step = _sign(destination.col - source.col)
    return Position(destination.row - row_step, destination.col - col_step)


# Only the new mover is ever shortened. Different colors capture at the
# meeting cell; same color stops one cell short of it.
def plan_route(
    active_motions: List[Motion], piece: Piece, source: Position, destination: Position
) -> RoutePlan:
    if not is_straight_line(source, destination):
        return RoutePlan(destination=destination, capture_target=None, is_blocked=False)

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
        return RoutePlan(destination=destination, capture_target=None, is_blocked=False)

    row_step = _sign(destination.row - source.row)
    col_step = _sign(destination.col - source.col)
    cells_reachable = math.floor(earliest_collision_ms / CELL_DURATION_MS + _CELL_EPSILON_MS)

    if blocking_motion.piece.color != piece.color:
        if cells_reachable < 1:
            return RoutePlan(destination=source, capture_target=None, is_blocked=True)
        capture_cell = Position(
            source.row + row_step * cells_reachable, source.col + col_step * cells_reachable
        )
        return RoutePlan(destination=capture_cell, capture_target=blocking_motion.piece, is_blocked=False)

    safe_cells = cells_reachable - 1
    if safe_cells < 1:
        return RoutePlan(destination=source, capture_target=None, is_blocked=True)
    safe_cell = Position(source.row + row_step * safe_cells, source.col + col_step * safe_cells)
    return RoutePlan(destination=safe_cell, capture_target=None, is_blocked=False)
