from config import CELL_SIZE
from engine.game_engine import GameSnapshot


class Renderer:
    def __init__(self, canvas):
        self._canvas = canvas

    def draw(self, snapshot: GameSnapshot) -> None:
        self._draw_grid(snapshot)
        self._draw_pieces(snapshot)
        self._draw_selection(snapshot)
        if snapshot.game_over:
            self._canvas.draw_text("Game Over", x=0, y=0)

    def _draw_grid(self, snapshot: GameSnapshot) -> None:
        for row in range(snapshot.board_height):
            for col in range(snapshot.board_width):
                self._canvas.draw_rect(x=col * CELL_SIZE, y=row * CELL_SIZE, width=CELL_SIZE, height=CELL_SIZE)

    # pixel_x/pixel_y already account for in-flight interpolation - the
    # renderer never needs to know whether a piece is moving.
    def _draw_pieces(self, snapshot: GameSnapshot) -> None:
        for piece in snapshot.pieces:
            self._canvas.draw_image(f"{piece.color}{piece.kind}", x=piece.pixel_x, y=piece.pixel_y)

    def _draw_selection(self, snapshot: GameSnapshot) -> None:
        if snapshot.selected_cell is not None:
            self._canvas.highlight_cell(row=snapshot.selected_cell.row, col=snapshot.selected_cell.col)
