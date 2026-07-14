import math
from dataclasses import dataclass
from typing import List, Optional

from model.board import BoardRepresentation
from model.piece import PieceRepresentation
from model.position import Position
from realtime.motion import Motion, Trajectory, collision_time_ms, is_straight_line, motion_duration_ms, move_cell_duration_ms

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


# The nearest open cell backing away from destination toward source - used
# when an arrival finds a teammate already at destination. Collision
# detection only ever compares two motions still in flight against each
# other, so it can miss a third piece that has, by the time this motion
# lands, already finished its own separate motion and come to rest
# somewhere along this path; walking back cell by cell (instead of
# assuming the one cell immediately before destination is free) keeps
# add_piece below from raising OccupiedCellError in that case. source
# itself is always the final fallback - it's the cell this piece is
# vacating, guaranteed empty once it does.
def retreat_cell(board: BoardRepresentation, source: Position, destination: Position) -> Position:
    if not is_straight_line(source, destination):
        return source
    row_step = _sign(destination.row - source.row)
    col_step = _sign(destination.col - source.col)
    position = Position(destination.row - row_step, destination.col - col_step)
    while position != source and board.get_piece(position) is not None:
        position = Position(position.row - row_step, position.col - col_step)
    return position


# Whoever is already moving has right of way: a new move that would cross
# an opposing color's active path is rejected outright, and the active
# motion continues untouched to its own original destination - it captures
# normally on arrival if the piece that tried to cross it never moved. A
# same-color conflict isn't a rejection, just a race - the new mover stops
# one cell short instead of overwriting a teammate.
def plan_route(
    active_motions: List[Motion], piece: PieceRepresentation, source: Position, destination: Position
) -> RoutePlan:
    if not is_straight_line(source, destination):
        return RoutePlan(destination=destination, is_blocked=False)

    requested = Trajectory(source, destination, motion_duration_ms(source, destination, piece))

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
    cells_reachable = math.floor(earliest_collision_ms / move_cell_duration_ms(piece) + _CELL_EPSILON_MS)

    safe_cells = cells_reachable - 1
    if safe_cells < 1:
        return RoutePlan(destination=source, is_blocked=True)
    safe_cell = Position(source.row + row_step * safe_cells, source.col + col_step * safe_cells)
    return RoutePlan(destination=safe_cell, is_blocked=False)
