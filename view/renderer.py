from typing import Dict, Optional

from display_config import CELL_SIZE, MAX_VISIBLE_MOVES_PER_PANEL
from model.piece import BLACK, WHITE
from view.ui_snapshot import UiSnapshot

_PANEL_LINE_HEIGHT_PX = 18
_PANEL_TEXT_MARGIN_PX = 10
_PANEL_FONT_SIZE = 0.5


# The counterpart text-only reader is boardio/board_printer.py's
# print_board() - it deliberately does NOT share this class's data source
# (GameSnapshot's interpolated positions have no honest ASCII-cell answer
# mid-motion); see its own docstring for why that's by design, not drift.
class Renderer:
    # player_names/side_panel_width_px/cell_size are all optional and default
    # to "no panels, the fixed default CELL_SIZE" - a Renderer built with
    # just a canvas behaves exactly as before panels (or a screen-derived
    # cell_size) existed. Both are caller-supplied constructor arguments
    # rather than reading config directly (same reasoning as
    # input.board_mapper.BoardMapper's cell_size) - the caller (see play.py)
    # must construct its ImgCanvas with the same width and cell_size, so
    # passing them explicitly makes that pairing visible at the call site
    # instead of modules silently agreeing via a shared import.
    #
    # No move_log/score here - unlike those, a Renderer's whole draw() input
    # is per-frame data (see view/ui_snapshot.py's UiSnapshot), not a
    # long-lived collaborator it reaches out to mid-draw. This class only
    # ever reads what draw() was handed.
    def __init__(
        self,
        canvas,
        player_names: Optional[Dict[str, str]] = None,
        side_panel_width_px: int = 0,
        max_visible_moves: int = MAX_VISIBLE_MOVES_PER_PANEL,
        cell_size: int = CELL_SIZE,
    ):
        self._canvas = canvas
        self._player_names = player_names if player_names is not None else {WHITE: "White", BLACK: "Black"}
        self._side_panel_width_px = side_panel_width_px
        self._max_visible_moves = max_visible_moves
        self._cell_size = cell_size

    # ui_snapshot.status_message is a one-line overlay for transient state
    # GameSnapshot itself carries no field for (e.g. play_online.py's own
    # opponent-disconnect countdown) - drawn below "Game Over" rather than
    # instead of it, since a disconnect countdown that just crossed into a
    # resignation can legitimately show both on the same frame.
    def draw(self, ui_snapshot: UiSnapshot) -> None:
        snapshot = ui_snapshot.game
        self._draw_grid(snapshot)
        self._draw_pieces(snapshot)
        self._draw_selection(snapshot)
        next_overlay_y = 0
        if snapshot.game_over:
            self._canvas.draw_text("Game Over", x=self._side_panel_width_px, y=next_overlay_y)
            next_overlay_y += _PANEL_LINE_HEIGHT_PX
        if ui_snapshot.status_message:
            self._canvas.draw_text(ui_snapshot.status_message, x=self._side_panel_width_px, y=next_overlay_y)
        self._draw_side_panels(ui_snapshot)

    def _draw_grid(self, snapshot) -> None:
        for row in range(snapshot.board_height):
            for col in range(snapshot.board_width):
                self._canvas.draw_rect(
                    x=col * self._cell_size, y=row * self._cell_size, width=self._cell_size, height=self._cell_size
                )

    # piece.row/piece.col already account for in-flight interpolation - the
    # renderer never needs to know whether a piece is moving. Converting
    # board coordinates to pixels is this layer's job, not the engine's -
    # the model only ever deals in board-relative row/col.
    def _draw_pieces(self, snapshot) -> None:
        for piece in snapshot.pieces:
            key = f"{piece.id}:{piece.color}:{piece.kind}:{piece.motion_phase}"
            x = int(piece.col * self._cell_size + self._cell_size // 2)
            y = int(piece.row * self._cell_size + self._cell_size // 2)
            self._canvas.draw_image(key, x=x, y=y)

    def _draw_selection(self, snapshot) -> None:
        if snapshot.selected_cell is not None:
            self._canvas.highlight_cell(row=snapshot.selected_cell.row, col=snapshot.selected_cell.col)

    # Purely cosmetic - reads whatever view/ui_snapshot.py's UiSnapshot
    # carries for this frame's move_log/score panels. Drawn in
    # canvas-frame-absolute coordinates (unlike draw_rect/draw_image/
    # highlight_cell, which are board-relative and offset internally by
    # view.canvas.img_canvas.ImgCanvas) since this text lives outside the
    # board entirely. No-op when no panel data was given at construction.
    def _draw_side_panels(self, ui_snapshot: UiSnapshot) -> None:
        if self._side_panel_width_px == 0:
            return

        board_width_px = ui_snapshot.game.board_width * self._cell_size
        right_panel_x = self._side_panel_width_px + board_width_px + _PANEL_TEXT_MARGIN_PX

        self._draw_panel(ui_snapshot, BLACK, x=_PANEL_TEXT_MARGIN_PX)
        self._draw_panel(ui_snapshot, WHITE, x=right_panel_x)

    def _draw_panel(self, ui_snapshot: UiSnapshot, color: str, x: int) -> None:
        lines = [
            self._player_names.get(color, color),
            f"Score: {ui_snapshot.score_by_color.get(color, 0)}",
            "Time      Move",
        ]
        for entry in ui_snapshot.move_log_by_color.get(color, [])[-self._max_visible_moves:]:
            lines.append(f"{_format_elapsed(entry.elapsed_ms)}  {entry.notation}")

        for line_index, line in enumerate(lines):
            y = line_index * _PANEL_LINE_HEIGHT_PX
            self._canvas.draw_text(line, x=x, y=y, font_size=_PANEL_FONT_SIZE)


def _format_elapsed(elapsed_ms: int) -> str:
    minutes, remainder_ms = divmod(elapsed_ms, 60_000)
    seconds, millis = divmod(remainder_ms, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
