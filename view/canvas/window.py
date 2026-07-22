import sys

import cv2

ESC_KEY = 27

_dpi_awareness_set = False


# Without this, on a Windows display with Scaling != 100% (common on
# laptops), the OS silently stretches the whole drawn window over more
# physical pixels than the image actually has - so mouse coordinates from
# cv2.setMouseCallback stop lining up 1:1 with a pixel in the board image,
# and BoardMapper (which assumes exactly that 1:1 mapping) reads the wrong
# cell. This tells Windows "give me physical pixels, don't stretch" -
# see debug_mouse.py, the tool that exists specifically to catch this class
# of bug. Must run before the first cv2.namedWindow. Idempotent: Windows
# only allows setting this once per process, so a second GameWindow in the
# same run (there isn't one today, but nothing here assumes it) must not
# call it again.
def _disable_windows_dpi_scaling() -> None:
    global _dpi_awareness_set
    if _dpi_awareness_set or sys.platform != "win32":
        return
    _dpi_awareness_set = True

    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


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
    problem that a resizable window would otherwise raise - see
    _disable_windows_dpi_scaling for the other half of that guarantee.
    """

    def __init__(self, title: str):
        _disable_windows_dpi_scaling()
        self._title = title
        # cv2 mouse event code -> the handler registered for it, e.g.
        # {cv2.EVENT_LBUTTONDOWN: <on_click handler>}. Absent (rather than
        # None) until on_click/on_jump/on_move register one, so _on_mouse
        # stays a single dict lookup instead of an event-by-event if/elif.
        self._handlers = {}
        cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(title, self._on_mouse)

    def on_click(self, handler) -> None:
        self._handlers[cv2.EVENT_LBUTTONDOWN] = handler

    # Right-click triggers a jump - the only in-game action besides an
    # ordinary move, and left-click is already taken for select/move.
    def on_jump(self, handler) -> None:
        self._handlers[cv2.EVENT_RBUTTONDOWN] = handler

    # Fires on every hover position, not just clicks - debug_mouse.py is
    # the only current user, to visually confirm pixel->cell mapping is
    # correct without waiting for a click.
    def on_move(self, handler) -> None:
        self._handlers[cv2.EVENT_MOUSEMOVE] = handler

    def _on_mouse(self, event, x, y, flags, userdata) -> None:
        handler = self._handlers.get(event)
        if handler is not None:
            handler(x, y)

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

    # If the user already closed the window via its own [X] button (not
    # Esc), cv2 already destroyed it internally - show() already treats
    # that same getWindowProperty check as "gone" (see above); calling
    # destroyWindow again on an already-gone window raises a NULL window
    # cv2.error, so this must check first rather than destroy unconditionally.
    def close(self) -> None:
        if cv2.getWindowProperty(self._title, cv2.WND_PROP_VISIBLE) >= 1:
            cv2.destroyWindow(self._title)
