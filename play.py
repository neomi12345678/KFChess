import time

from game_builder import build_app
from view.canvas.window import GameWindow


def main(white_name: str = "White", black_name: str = "Black") -> None:  # pragma: no cover
    app, game_engine, canvas = build_app(white_name, black_name)

    window = GameWindow("KFChess")
    window.on_click(app.on_click)
    window.on_jump(app.on_jump)

    last_tick = time.monotonic()
    # Truncating each frame's elapsed time to whole milliseconds and
    # discarding the remainder would make the simulated clock drift behind
    # the wall clock - carry the fractional remainder into the next frame
    # instead so nothing is lost.
    carried_ms = 0.0
    running = True
    while running:
        now = time.monotonic()
        elapsed_ms = (now - last_tick) * 1000 + carried_ms
        whole_ms = int(elapsed_ms)
        carried_ms = elapsed_ms - whole_ms
        last_tick = now
        game_engine.wait(whole_ms)

        canvas.begin_frame()
        app.render()
        running = window.show(canvas.frame())

    window.close()


if __name__ == "__main__":  # pragma: no cover
    main()
