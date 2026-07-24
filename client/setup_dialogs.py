"""GUI (tkinter) replacement for play_online.py's old terminal login/
matchmaking prompts. Runs entirely before the real game window opens (see
view/canvas/window.py's GameWindow, built on cv2 - which has no text-entry
or button widgets of its own, hence tkinter here instead) and is fully torn
down before that window is created.

Both dialogs below share a single Tk() root (see _get_root) so the two
steps read as one app - a login screen, then a play/create/join screen -
rather than two separate OS windows opening and closing back to back.

Each network call that can take a while (login, and especially matchmaking's
wait_for_seat, which can block for up to a minute) runs on a short-lived
daemon background thread; the Tk mainloop only ever polls a queue.Queue for
the result (via root.after) so the window stays responsive the whole time -
the same "background thread blocks, GUI thread only polls" split
client/network_client.py's NetworkGameClient already uses internally for the
websocket connection itself.

Not unit-tested: like GameWindow, this opens a real OS window and drives a
real Tk event loop - nothing here to exercise without one. The accept/
reject/timeout branching mirrors the old terminal prompts exactly and stays
covered at the NetworkGameClient level by tests/integration/test_network_client.py.
"""

import gc
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from client.network_client import MatchmakingTimeoutError, NetworkClientError, NetworkGameClient
from protocol.lobby_messages import LoginAckMessage
from protocol.types import Role

_root: Optional[tk.Tk] = None


class SetupCancelled(Exception):
    """Raised when the player closes the setup window or clicks Cancel -
    play_online.py's main() catches this to exit quietly instead of
    crashing, the GUI equivalent of the terminal flow's Ctrl+C escape hatch."""


# Lazily creates the one Tk() root both dialogs below share, so the window
# never has to visibly close and reopen between the login step and the
# play/create/join step - just its contents change.
def _get_root() -> tk.Tk:
    global _root
    if _root is None:
        _root = tk.Tk()
        _root.resizable(False, False)
    return _root


def _destroy_root() -> None:
    global _root
    if _root is not None:
        _root.destroy()
        _root = None
        _collect_dialog_garbage()


# Every button/entry built below carries a Tcl-registered command closure
# that (via the shared `controls` list each closure closes over) refers
# back to the very widgets it's bound to - a real reference cycle plain
# refcounting can never collect, only Python's cyclic GC pass can, and only
# whenever that next happens to run. Left uncollected, this garbage floats
# until *some* thread's allocations cross the GC threshold - and once the
# real (cv2) game window is up, play_online.py's NetworkGameClient
# background thread is already running and allocating constantly (parsing
# every server broadcast), so it's the one at risk of winning that race. A
# StringVar's __del__ then calling back into a Tcl interpreter that's
# already been destroy()'d, from a thread Tcl doesn't consider "the main
# thread", is exactly what produces "Tcl_AsyncDelete: async handler deleted
# by the wrong thread" - fatal on some Tcl builds. Forcing the collection
# here instead - synchronously, on this thread, right after the widgets
# that formed the cycle are torn down - keeps this deterministic instead of
# a race against that background thread.
def _collect_dialog_garbage() -> None:
    gc.collect()


def _set_widgets_enabled(widgets: List[tk.Widget], enabled: bool) -> None:
    state = "normal" if enabled else "disabled"
    for widget in widgets:
        widget.configure(state=state)


# Prompts for username/password, mirroring the old _prompt_login's "loop on
# rejection, let them try again" UX. Returns the accepted LoginAckMessage, or
# raises SetupCancelled if the window is closed. Does NOT destroy the root
# on success - run_game_setup (the only caller that ever follows a
# successful login) reuses the same window.
def run_login(client: NetworkGameClient) -> LoginAckMessage:
    root = _get_root()
    root.title("KFChess Login")
    for child in root.winfo_children():
        child.destroy()

    frame = ttk.Frame(root, padding=16)
    frame.grid()

    outcome: dict = {}
    result_queue: "queue.Queue[tuple]" = queue.Queue()

    ttk.Label(frame, text="Username").grid(column=0, row=0, sticky="w")
    username_var = tk.StringVar()
    username_entry = ttk.Entry(frame, textvariable=username_var, width=28)
    username_entry.grid(column=0, row=1, pady=(0, 8))

    ttk.Label(frame, text="Password").grid(column=0, row=2, sticky="w")
    password_var = tk.StringVar()
    password_entry = ttk.Entry(frame, textvariable=password_var, width=28, show="*")
    password_entry.grid(column=0, row=3, pady=(0, 8))

    status_var = tk.StringVar()
    ttk.Label(frame, textvariable=status_var, foreground="#b00020", wraplength=220).grid(column=0, row=4, sticky="w")

    login_button = ttk.Button(frame, text="Log in")
    login_button.grid(column=0, row=5, pady=(8, 0), sticky="e")

    controls = [username_entry, password_entry, login_button]

    def submit(event=None) -> None:
        username = username_var.get().strip()
        password = password_var.get()
        if not username or not password:
            status_var.set("Enter a username and password.")
            return

        _set_widgets_enabled(controls, enabled=False)
        status_var.set("Logging in...")

        def worker() -> None:
            try:
                result_queue.put(("ok", client.login(username, password)))
            except NetworkClientError as error:
                result_queue.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def poll() -> None:
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            root.after(50, poll)
            return

        # A connection error or a rejected login both let the player retry
        # (re-enabled controls above are exactly what submit() needs to fire
        # again) - so, unlike an accepted login below, this must keep
        # polling: nothing else ever reschedules poll() once this call
        # returns, and a later submit() only ever puts a new result on
        # result_queue, it doesn't restart the polling loop itself.
        if kind == "error":
            _set_widgets_enabled(controls, enabled=True)
            status_var.set(f"Connection error: {payload}")
            root.after(50, poll)
            return

        if not payload.accepted:
            _set_widgets_enabled(controls, enabled=True)
            status_var.set(f"Login failed: {payload.reason}")
            root.after(50, poll)
            return

        outcome["value"] = payload
        root.quit()

    def cancel() -> None:
        outcome["cancelled"] = True
        root.quit()

    login_button.configure(command=submit)
    username_entry.bind("<Return>", submit)
    password_entry.bind("<Return>", submit)
    root.protocol("WM_DELETE_WINDOW", cancel)

    username_entry.focus_set()
    root.after(50, poll)
    root.mainloop()

    if outcome.get("cancelled"):
        _destroy_root()
        raise SetupCancelled()
    return outcome["value"]


# Mirrors the old _prompt_for_game: "play" queues for matchmaking, "create"
# opens a room and waits for an opponent, "join <id>" joins one (returning
# None if the server seats us as a spectator rather than an opponent).
# Always destroys the shared root before returning/raising - this is always
# the last GUI screen before the real (cv2) game window opens.
def run_game_setup(client: NetworkGameClient) -> Optional[str]:
    root = _get_root()
    root.title("Play KFChess")
    for child in root.winfo_children():
        child.destroy()
    # run_login's own widgets/closures just became unreachable above, and
    # form the same reference cycle _collect_dialog_garbage's own docstring
    # describes - collected here too, for the same reason: client.login()
    # already ran on a background thread by this point, so there's already
    # something racing to collect this garbage on the wrong thread instead.
    _collect_dialog_garbage()

    frame = ttk.Frame(root, padding=16)
    frame.grid()

    outcome: dict = {}
    result_queue: "queue.Queue[tuple]" = queue.Queue()

    play_button = ttk.Button(frame, text="Play")
    play_button.grid(column=0, row=0, columnspan=3, sticky="ew", pady=(0, 12))

    ttk.Separator(frame, orient="horizontal").grid(column=0, row=1, columnspan=3, sticky="ew", pady=(0, 12))

    ttk.Label(frame, text="Room name").grid(column=0, row=2, columnspan=3, sticky="w")
    room_id_var = tk.StringVar()
    room_entry = ttk.Entry(frame, textvariable=room_id_var, width=18)
    room_entry.grid(column=0, row=3, sticky="w")

    create_button = ttk.Button(frame, text="Create")
    create_button.grid(column=1, row=3, padx=(6, 0))
    join_button = ttk.Button(frame, text="Join")
    join_button.grid(column=2, row=3, padx=(6, 0))

    status_var = tk.StringVar()
    ttk.Label(frame, textvariable=status_var, wraplength=260).grid(column=0, row=4, columnspan=3, sticky="w", pady=(10, 0))

    cancel_button = ttk.Button(frame, text="Cancel")
    cancel_button.grid(column=0, row=5, columnspan=3, pady=(12, 0), sticky="ew")

    controls = [play_button, room_entry, create_button, join_button]

    def busy(status_text: str) -> None:
        _set_widgets_enabled(controls, enabled=False)
        status_var.set(status_text)

    def idle(status_text: str) -> None:
        _set_widgets_enabled(controls, enabled=True)
        status_var.set(status_text)

    def start(worker) -> None:
        threading.Thread(target=worker, daemon=True).start()

    def do_play() -> None:
        busy("Searching for an opponent...")

        def worker() -> None:
            play_ack = client.play()
            if not play_ack.accepted:
                result_queue.put(("retry", f"Could not queue: {play_ack.reason}"))
                return
            try:
                seat_message = client.wait_for_seat()
            except MatchmakingTimeoutError:
                result_queue.put(("retry", "No opponent found in time - try again."))
                return
            except NetworkClientError:
                result_queue.put(("retry", "Lost connection while waiting for a match."))
                return
            result_queue.put(("seated", seat_message.color))

        start(worker)

    def do_create() -> None:
        busy("Creating room...")

        def worker() -> None:
            create_ack = client.create_room()
            if not create_ack.accepted:
                result_queue.put(("retry", f"Could not create a room: {create_ack.reason}"))
                return
            room_id = create_ack.room_id
            result_queue.put(("room_created", room_id))
            result_queue.put(("info", f"Room created: {room_id} - waiting for an opponent..."))
            try:
                # No fixed timeout on the wire for this (unlike PLAY's own
                # matchmaking_timeout) - a room just waits until someone
                # joins or the player closes this window. Mirrors the old
                # terminal flow's own day-long stand-in for "indefinitely".
                seat_message = client.wait_for_seat(timeout=86_400.0)
            except NetworkClientError:
                result_queue.put(("retry", "Lost connection while waiting for an opponent."))
                return
            result_queue.put(("seated", seat_message.color))

        start(worker)

    def do_join() -> None:
        room_id = room_id_var.get().strip()
        if not room_id:
            status_var.set("Enter a room id to join.")
            return

        busy(f"Joining room {room_id}...")

        def worker() -> None:
            join_ack = client.join_room(room_id)
            if not join_ack.accepted:
                result_queue.put(("retry", f"Could not join room {room_id}: {join_ack.reason}"))
                return
            if join_ack.role == Role.SPECTATOR:
                result_queue.put(("spectate", None))
                return
            result_queue.put(("info", f"Joined room {room_id} - waiting to be seated..."))
            try:
                seat_message = client.wait_for_seat()
            except NetworkClientError:
                result_queue.put(("retry", "Lost connection while waiting to be seated."))
                return
            result_queue.put(("seated", seat_message.color))

        start(worker)

    def _handle_info(payload) -> None:
        status_var.set(payload)

    def _handle_room_created(payload) -> None:
        # Create ignores whatever was typed in the field (the server
        # always assigns its own id, see server/rooms.py) - filling it
        # in with the real id here (read-only, so it reads as assigned
        # rather than editable) is what makes that id available to type
        # into a Join elsewhere, instead of only ever showing up in the
        # status label below.
        room_id_var.set(payload)
        room_entry.configure(state="readonly")

    def _handle_retry(payload) -> None:
        idle(payload)

    def _handle_spectate(payload) -> None:
        outcome["value"] = None
        root.quit()

    def _handle_seated(payload) -> None:
        outcome["value"] = payload
        root.quit()

    # result_queue's kind -> handler. "spectate"/"seated" end the dialog
    # (root.quit()), so they're also the ones poll() must not reschedule
    # itself after - see _ENDING_KINDS below.
    _KIND_HANDLERS = {
        "info": _handle_info,
        "room_created": _handle_room_created,
        "retry": _handle_retry,
        "spectate": _handle_spectate,
        "seated": _handle_seated,
    }
    _ENDING_KINDS = {"spectate", "seated"}

    def poll() -> None:
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            root.after(50, poll)
            return

        _KIND_HANDLERS[kind](payload)
        if kind not in _ENDING_KINDS:
            root.after(50, poll)

    def cancel() -> None:
        outcome["cancelled"] = True
        root.quit()

    play_button.configure(command=do_play)
    create_button.configure(command=do_create)
    join_button.configure(command=do_join)
    room_entry.bind("<Return>", lambda event: do_join())
    cancel_button.configure(command=cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)

    root.after(50, poll)
    root.mainloop()
    _destroy_root()

    if outcome.get("cancelled"):
        raise SetupCancelled()
    return outcome["value"]
