from app_builder import build_app
from frame_clock import FrameClock
from view.canvas.window import GameWindow


def main(white_name: str = "White", black_name: str = "Black") -> None:  # pragma: no cover
    app, game_engine, canvas = build_app(white_name, black_name)

    window = GameWindow("KFChess")
    window.on_click(app.on_click)
    window.on_jump(app.on_jump)

    clock = FrameClock()
    running = True
    while running:
        game_engine.wait(clock.tick())

        canvas.begin_frame()
        app.render()
        running = window.show(canvas.frame())

    window.close()


if __name__ == "__main__":  # pragma: no cover
    main()
