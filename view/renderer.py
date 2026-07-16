from typing import Dict, Optional

from display_config import CELL_SIZE, MAX_VISIBLE_MOVES_PER_PANEL
from model.game_state import GameSnapshot
from model.piece import BLACK, WHITE
from view.observers import MoveLogObserver, ScoreObserver

_PANEL_LINE_HEIGHT_PX = 18
_PANEL_TEXT_MARGIN_PX = 10
_PANEL_FONT_SIZE = 0.5


# The counterpart text-only reader is boardio/board_printer.py's
# print_board() - it deliberately does NOT share this class's data source
# (GameSnapshot's interpolated positions have no honest ASCII-cell answer
# mid-motion); see its own docstring for why that's by design, not drift.
class Renderer:
    # move_log/score/player_names/side_panel_width_px/cell_size are all
    # optional and default to "no panels, the fixed default CELL_SIZE" - a
    # Renderer built with just a canvas behaves exactly as before panels (or
    # a screen-derived cell_size) existed. Both are caller-supplied
    # constructor arguments rather than reading config directly (same
    # reasoning as input.board_mapper.BoardMapper's cell_size) - the caller
    # (see play.py) must construct its ImgCanvas with the same width and
    # cell_size, so passing them explicitly makes that pairing visible at
    # the call site instead of modules silently agreeing via a shared import.
    def __init__(
        self,
        canvas,
        move_log: Optional[MoveLogObserver] = None,
        score: Optional[ScoreObserver] = None,
        player_names: Optional[Dict[str, str]] = None,
        side_panel_width_px: int = 0,
        max_visible_moves: int = MAX_VISIBLE_MOVES_PER_PANEL,
        cell_size: int = CELL_SIZE,
    ):
        self._canvas = canvas
        self._move_log = move_log
        self._score = score
        self._player_names = player_names if player_names is not None else {WHITE: "White", BLACK: "Black"}
        self._side_panel_width_px = side_panel_width_px
        self._max_visible_moves = max_visible_moves
        self._cell_size = cell_size

    def draw(self, snapshot: GameSnapshot) -> None:
        self._draw_grid(snapshot)
        self._draw_pieces(snapshot)
        self._draw_selection(snapshot)
        if snapshot.game_over:
            self._canvas.draw_text("Game Over", x=self._side_panel_width_px, y=0)
        self._draw_side_panels(snapshot)

    def _draw_grid(self, snapshot: GameSnapshot) -> None:
        for row in range(snapshot.board_height):
            for col in range(snapshot.board_width):
                self._canvas.draw_rect(
                    x=col * self._cell_size, y=row * self._cell_size, width=self._cell_size, height=self._cell_size
                )

    # piece.row/piece.col already account for in-flight interpolation - the
    # renderer never needs to know whether a piece is moving. Converting
    # board coordinates to pixels is this layer's job, not the engine's -
    # the model only ever deals in board-relative row/col.
    def _draw_pieces(self, snapshot: GameSnapshot) -> None:
        for piece in snapshot.pieces:
            key = f"{piece.id}:{piece.color}:{piece.kind}:{piece.motion_phase}"
            x = int(piece.col * self._cell_size + self._cell_size // 2)
            y = int(piece.row * self._cell_size + self._cell_size // 2)
            self._canvas.draw_image(key, x=x, y=y)

    def _draw_selection(self, snapshot: GameSnapshot) -> None:
        if snapshot.selected_cell is not None:
            self._canvas.highlight_cell(row=snapshot.selected_cell.row, col=snapshot.selected_cell.col)

    # Purely cosmetic - reads back whatever view.observers.MoveLogObserver/
    # ScoreObserver have accumulated so far, at this frame's own pace. Drawn
    # in canvas-frame-absolute coordinates (unlike draw_rect/draw_image/
    # highlight_cell, which are board-relative and offset internally by
    # view.canvas.img_canvas.ImgCanvas) since this text lives outside the board
    # entirely. No-op when no panel data was given at construction.
    def _draw_side_panels(self, snapshot: GameSnapshot) -> None:
        if self._side_panel_width_px == 0:
            return

        board_width_px = snapshot.board_width * self._cell_size
        right_panel_x = self._side_panel_width_px + board_width_px + _PANEL_TEXT_MARGIN_PX

        self._draw_panel(BLACK, x=_PANEL_TEXT_MARGIN_PX)
        self._draw_panel(WHITE, x=right_panel_x)

    def _draw_panel(self, color: str, x: int) -> None:
        lines = [
            self._player_names.get(color, color),
            f"Score: {self._score.score_for(color) if self._score is not None else 0}",
            "Time      Move",
        ]
        if self._move_log is not None:
            for entry in self._move_log.entries_for(color)[-self._max_visible_moves:]:
                lines.append(f"{_format_elapsed(entry.elapsed_ms)}  {entry.notation}")

        for line_index, line in enumerate(lines):
            y = line_index * _PANEL_LINE_HEIGHT_PX
            self._canvas.draw_text(line, x=x, y=y, font_size=_PANEL_FONT_SIZE)


def _format_elapsed(elapsed_ms: int) -> str:
    minutes, remainder_ms = divmod(elapsed_ms, 60_000)
    seconds, millis = divmod(remainder_ms, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
