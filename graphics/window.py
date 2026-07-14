import cv2

ESC_KEY = 27


class GameWindow:
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
        cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(title, self._on_mouse)

    def on_click(self, handler) -> None:
        self._click_handler = handler

    # Right-click triggers a jump - the only in-game action besides an
    # ordinary move, and left-click is already taken for select/move.
    def on_jump(self, handler) -> None:
        self._jump_handler = handler

    def _on_mouse(self, event, x, y, flags, userdata) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and self._click_handler is not None:
            self._click_handler(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN and self._jump_handler is not None:
            self._jump_handler(x, y)

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
