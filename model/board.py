from typing import Dict, Optional, Protocol, Set

from model.piece import Piece, PieceRepresentation
from model.position import Position


class OccupiedCellError(Exception):
    def __init__(self, position: Position):
        super().__init__(f"cell already occupied: {position}")
        self.position = position


class DuplicatePieceIdError(Exception):
    def __init__(self, piece_id: str):
        super().__init__(f"duplicate piece id: {piece_id}")
        self.piece_id = piece_id


class BoardQuery(Protocol):
    """The read-only contract: bounds + lookup.

    Every consumer that only ever reads the board - rules/board_rules.py,
    rules/piece_rules.py, rules/rule_engine.py, realtime/route_planner.py,
    boardio/board_printer.py, engine/game_engine.py - depends on just this,
    never on BoardMutator/BoardStore below, so a future binary/bitboard
    representation only has to implement these four members to work
    everywhere game logic reads a board.
    """

    width: int
    height: int

    def is_in_bounds(self, position: Position) -> bool: ...

    def get_piece(self, position: Position) -> Optional[PieceRepresentation]: ...


class BoardMutator(Protocol):
    """The write contract: exactly what realtime/real_time_arbiter.py's
    RealTimeArbiter calls when a motion resolves - always add_piece/
    remove_piece as a pair (see _resolve_arrival), never a relocate-in-place
    call, so that's all this asks for.
    """

    def add_piece(self, position: Position, piece: PieceRepresentation) -> None: ...

    def remove_piece(self, position: Position) -> None: ...


class BoardStore(BoardQuery, BoardMutator, Protocol):
    """The full board contract - only for whoever owns/constructs the one
    shared board instance and hands it to both a read-only consumer and
    RealTimeArbiter's mutator: engine/game_builder.py's build_game,
    server/session.py's GameSession, server/game_loop.py and
    server/ws_server.py's board_factory.
    """


class Board:
    """The standard in-memory BoardStore: cells kept in a dict.

    move_piece is an extra convenience beyond BoardStore's own contract -
    no production consumer needs it (RealTimeArbiter always does
    remove_piece+add_piece as a pair instead, see _resolve_arrival), only
    tests exercise it directly against this concrete class.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._cells: Dict[Position, Piece] = {}
        self._piece_ids: Set[str] = set()

    def is_in_bounds(self, position: Position) -> bool:
        return 0 <= position.row < self.height and 0 <= position.col < self.width

    def get_piece(self, position: Position) -> Optional[Piece]:
        return self._cells.get(position)

    def add_piece(self, position: Position, piece: Piece) -> None:
        # Fail loudly on an unexpected occupant instead of silently
        # overwriting it - callers must resolve captures themselves first.
        if position in self._cells:
            raise OccupiedCellError(position)
        if piece.id in self._piece_ids:
            raise DuplicatePieceIdError(piece.id)
        piece.cell = position
        self._cells[position] = piece
        self._piece_ids.add(piece.id)

    def remove_piece(self, position: Position) -> None:
        piece = self._cells.pop(position)
        self._piece_ids.discard(piece.id)

    def move_piece(self, src: Position, dst: Position) -> None:
        # Same fail-loud guarantee as add_piece: relocating onto an
        # occupied cell is a bug at the call site, not something to hide.
        if dst in self._cells:
            raise OccupiedCellError(dst)
        piece = self._cells.pop(src)
        piece.cell = dst
        self._cells[dst] = piece
