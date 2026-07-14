import cv2

ESC_KEY = 27


# Not unit-tested: __init__ opens a real OS window as a side effect
# (cv2.namedWindow), and show()/close() drive that same real window and its
# live event queue - there's no way to exercise this class without either
# a real display or mocking cv2, and this project's tests use real objects
# only, never mocks. Covered instead by actually running play.py (see the
# `run` skill) and clicking through it by hand.
class GameWindow:  # pragma: no cover
    """The only place cv2's window/event-loop primitives are touched
    directly - everything else in the app talks to ImgCanvas/Img.

    Fixed-size (WINDOW_AUTOSIZE): mouse coordinates from cv2 then map 1:1
    onto image pixels, sidestepping the screen-pixels-vs-image-pixels
    problem that a resizable window would otherwise raise.
    """

    def __init__(self, title: str):
        self._title = title
        self._click_handler = None
        self._jump_handler = None
        self._move_handler = None
        cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(title, self._on_mouse)

    def on_click(self, handler) -> None:
        self._click_handler = handler

    # Right-click triggers a jump - the only in-game action besides an
    # ordinary move, and left-click is already taken for select/move.
    def on_jump(self, handler) -> None:
        self._jump_handler = handler

    # Fires on every hover position, not just clicks - debug_mouse.py is
    # the only current user, to visually confirm pixel->cell mapping is
    # correct without waiting for a click.
    def on_move(self, handler) -> None:
        self._move_handler = handler

    def _on_mouse(self, event, x, y, flags, userdata) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and self._click_handler is not None:
            self._click_handler(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN and self._jump_handler is not None:
            self._jump_handler(x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self._move_handler is not None:
            self._move_handler(x, y)

    # Displays one frame and pumps the event queue (mouse callback, key
    # presses). Returns False once the user closes the window or hits Esc.
    def show(self, frame) -> bool:
        cv2.imshow(self._title, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ESC_KEY:
            return False
        if cv2.getWindowProperty(self._title, cv2.WND_PROP_VISIBLE) < 1:
            return False
        return True

    def close(self) -> None:
        cv2.destroyWindow(self._title)
