"""GUI-side click/jump selection logic for the networked client
(play_online.py) - the counterpart to input/controller.py's Controller,
but working off the last-received GameSnapshot (see server/protocol.py's
snapshot_from_json) instead of a live GameEngine, since there's no local
Board to query over the network. Legality is still entirely the server's
call (see server/session.py's apply_command) - a rejected MoveRequest/
JumpRequest here just never visibly moves anything once the next
broadcast arrives. This only ever decides "what should the next click
select or send", the same UX role Controller plays for the local GUI.

Piece identity, not just cell, is what a second click reconfirms before
acting (mirroring Controller's own reasoning) - real wall-clock time
passes between two clicks here too, and the piece originally selected may
have moved/been captured by the time the second click arrives.
"""

from dataclasses import dataclass
from typing import Optional, Union

from model.game_state import GameSnapshot, PieceSnapshot
from model.piece import PHASE_IDLE
from model.position import Position


@dataclass(frozen=True)
class MoveRequest:
    source: Position
    destination: Position


@dataclass(frozen=True)
class JumpRequest:
    position: Position


class NetworkController:
    def __init__(self, my_color: str):
        self._my_color = my_color
        self.selected: Optional[Position] = None
        self._selected_piece_id: Optional[str] = None

    def click(self, cell: Optional[Position], snapshot: GameSnapshot) -> Optional[MoveRequest]:
        if cell is None:
            self._clear()
            return None

        if self.selected is None:
            self._select_if_possible(cell, snapshot)
            return None

        current = _piece_at(snapshot, self.selected)
        if current is None or current.id != self._selected_piece_id:
            self._clear()
            return None

        # Switch selection to a same-color piece instead of attempting an
        # always-illegal move against it - unless it's currently
        # unselectable (mid-motion, airborne, or resting), in which case
        # the *original* selection must survive, not be cleared - the same
        # reasoning as input/controller.py's Controller.click.
        target = _piece_at(snapshot, cell)
        if target is not None and target.color == self._my_color:
            self._select_if_possible(cell, snapshot)
            return None

        source = self.selected
        self._clear()
        return MoveRequest(source=source, destination=cell)

    # Single-click, not click/click select-then-target - clears any leftover
    # selection first, the same way input/controller.py's Controller.jump
    # does, so it can't hijack the next click as a move.
    def jump(self, cell: Optional[Position]) -> Optional[JumpRequest]:
        self._clear()
        if cell is None:
            return None
        return JumpRequest(position=cell)

    def _select_if_possible(self, cell: Position, snapshot: GameSnapshot) -> None:
        piece = _piece_at(snapshot, cell)
        # motion_phase == PHASE_IDLE alone covers every reason GameEngine.
        # can_select would otherwise reject a piece for (moving, airborne,
        # resting) - see model/game_state.py's PieceSnapshot docstring: none
        # of those ever report PHASE_IDLE.
        if piece is not None and piece.color == self._my_color and piece.motion_phase == PHASE_IDLE:
            self.selected = cell
            self._selected_piece_id = piece.id

    def _clear(self) -> None:
        self.selected = None
        self._selected_piece_id = None


def _piece_at(snapshot: GameSnapshot, cell: Position) -> Optional[PieceSnapshot]:
    for piece in snapshot.pieces:
        if round(piece.row) == cell.row and round(piece.col) == cell.col:
            return piece
    return None
