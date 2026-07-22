from typing import Dict, Optional

from display_config import CELL_SIZE, MAX_VISIBLE_MOVES_PER_PANEL
from model.piece import BLACK, WHITE
from view.ui_snapshot import UiSnapshot

_PANEL_LINE_HEIGHT_PX = 18
_PANEL_TEXT_MARGIN_PX = 10
_PANEL_FONT_SIZE = 0.5
_PANEL_TITLE_FONT_SIZE = 0.6

# The card's own inner padding, and how far right the "MOVE" column starts
# from the same left edge "TIME" (and the name/score lines above it) use -
# see _draw_panel. Kept separate from _PANEL_TEXT_MARGIN_PX (the margin
# between the board/screen edge and the card itself) since that one
# positions the whole card, not text within it.
_CARD_PADDING_PX = 8
_MOVE_COLUMN_OFFSET_PX = 90

# BGR, matching every other color this module's canvas calls take (see
# view/canvas/img_canvas.py's draw_cooldown_bar). _GOLD is the exact same
# yellow view/canvas/img_canvas.py's highlight_cell already uses for the
# selected-square highlight (0, 255, 255) - one accent color for "this is
# the highlighted/important thing" across the whole board+panel view,
# rather than a second, only-slightly-different gold invented for the panel
# alone. Approximates the dark-card look a moves-log panel should have: a
# near-black card with faintly alternating row stripes so a long moves list
# stays easy to scan line-by-line - no border around the card itself (see
# _draw_panel), just the background fill.
_GOLD = (0, 255, 255)
_CARD_BG = (18, 18, 18)
_HEADER_ROW_BG = (35, 28, 8)
_ROW_BG_EVEN = (14, 14, 14)
_ROW_BG_ODD = (26, 26, 26)
_WHITE_TEXT = (255, 255, 255, 255)


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
    # player_names defaults to empty rather than a "White"/"Black" placeholder
    # - a color missing from it just gets no name line at all (see
    # _draw_panel), so a caller with no real name to show (e.g. play_online.py
    # before the server's own broadcast has told it who it's playing) doesn't
    # have to invent one. Local play (game_builder.py's build_app) always
    # passes real names explicitly, defaulting to "White"/"Black" itself -
    # this class has no opinion on what a good default name is, only on
    # whether to draw a name line at all.
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
        self._player_names = player_names if player_names is not None else {}
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
        self._draw_cooldown_bars(snapshot)
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

    # A depleting bar on every piece still airborne/short_rest/long_rest
    # (see model.piece.PHASE_JUMP/PHASE_SHORT_REST/PHASE_LONG_REST and
    # RealTimeArbiter.unavailable_progress) - a per-piece cooldown clock,
    # separate from _draw_selection's click-time square highlight above.
    # cooldown_total_ms is 0 for every piece not unavailable, so this only
    # ever draws for the ones that are.
    def _draw_cooldown_bars(self, snapshot) -> None:
        for piece in snapshot.pieces:
            if piece.cooldown_total_ms <= 0:
                continue
            fraction = piece.cooldown_remaining_ms / piece.cooldown_total_ms
            self._canvas.draw_cooldown_bar(row=int(piece.row), col=int(piece.col), fraction=fraction)

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
        # None (not "White"/"Black"/the raw color string) when this Renderer
        # was never told a real name for this color - see __init__'s own
        # comment on why player_names defaults to empty. Skipping the name
        # line entirely (rather than falling back to a placeholder) is what
        # lets a networked client that hasn't heard the server's real
        # usernames yet show a plain score/moves card instead of a lie.
        name = self._player_names.get(color)
        moves = ui_snapshot.move_log_by_color.get(color, [])[-self._max_visible_moves:]

        line_count = (1 if name else 0) + 1 + 1 + len(moves)  # [name?] + score + header + one row per move
        card_width = self._side_panel_width_px - 2 * _PANEL_TEXT_MARGIN_PX
        card_height = line_count * _PANEL_LINE_HEIGHT_PX + 2 * _CARD_PADDING_PX
        self._canvas.fill_rect(x, 0, card_width, card_height, color=_CARD_BG)

        text_x = x + _CARD_PADDING_PX
        move_x = text_x + _MOVE_COLUMN_OFFSET_PX
        y = _CARD_PADDING_PX

        if name:
            self._canvas.draw_text(name, x=text_x, y=y, font_size=_PANEL_TITLE_FONT_SIZE, color=_GOLD)
            y += _PANEL_LINE_HEIGHT_PX

        self._canvas.draw_text(
            f"Score: {ui_snapshot.score_by_color.get(color, 0)}", x=text_x, y=y, font_size=_PANEL_FONT_SIZE,
            color=_WHITE_TEXT,
        )
        y += _PANEL_LINE_HEIGHT_PX

        self._canvas.fill_rect(x, y, card_width, _PANEL_LINE_HEIGHT_PX, color=_HEADER_ROW_BG)
        self._canvas.draw_text("TIME", x=text_x, y=y, font_size=_PANEL_FONT_SIZE, color=_GOLD)
        self._canvas.draw_text("MOVE", x=move_x, y=y, font_size=_PANEL_FONT_SIZE, color=_GOLD)
        y += _PANEL_LINE_HEIGHT_PX

        for row_index, entry in enumerate(moves):
            row_bg = _ROW_BG_EVEN if row_index % 2 == 0 else _ROW_BG_ODD
            self._canvas.fill_rect(x, y, card_width, _PANEL_LINE_HEIGHT_PX, color=row_bg)
            self._canvas.draw_text(
                _format_elapsed(entry.elapsed_ms), x=text_x, y=y, font_size=_PANEL_FONT_SIZE, color=_WHITE_TEXT
            )
            self._canvas.draw_text(entry.notation, x=move_x, y=y, font_size=_PANEL_FONT_SIZE, color=_WHITE_TEXT)
            y += _PANEL_LINE_HEIGHT_PX


def _format_elapsed(elapsed_ms: int) -> str:
    minutes, remainder_ms = divmod(elapsed_ms, 60_000)
    seconds, millis = divmod(remainder_ms, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"
