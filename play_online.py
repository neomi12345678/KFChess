"""Networked counterpart to play.py: same graphical window/renderer, but
driven by the server (see server/ws_server.py) over WebSocket instead of a
local GameEngine. Login and matchmaking/room setup happen in the terminal
before the window opens (the Home screen's own "shell, not GUI" login step
- see client/client_cli.py, the text-only equivalent of this); once
seated, this renders whatever server/protocol.py's snapshot broadcasts say
the board looks like, and turns clicks into wire commands via
client/network_controller.py instead of a local Controller. A room
(server/rooms.py) joined as a spectator instead of the opponent renders
the exact same way, minus any click handling - see is_spectator below.

The moves-log/score side panels, the sound/animation Bus, and the two
transient status banners (disconnect countdown, a rejected move) are all
owned by client/game_view_state.py's GameViewState, not this module - see
its own docstring for why that state (and the message-dispatch logic that
updates it) lives there instead of as locals/closures in main() below:
mainly so it can be unit-tested without a real GameWindow/canvas/renderer.
main() here is only ever responsible for the terminal login/matchmaking
step, wiring GameViewState up to a real NetworkGameClient/GameWindow, and
driving the render loop - never for deciding what any wire message means.

Run: python play_online.py
"""

import dataclasses
import getpass
import time
from typing import Optional

import piece_config
from boardio.algebraic_notation import square_name
from client.game_view_state import GameViewState
from client.network_client import MatchmakingTimeoutError, NetworkClientError, NetworkGameClient
from client.network_controller import JumpRequest, MoveRequest, NetworkController
from display_config import compute_cell_size, screen_resolution_px, side_panel_width_for
from input.board_mapper import BoardMapper
from model.piece import BLACK, WHITE
from view.canvas.img_canvas import ImgCanvas
from view.canvas.window import GameWindow
from view.renderer import Renderer
from view.ui_snapshot import build_ui_snapshot

HOST = "localhost"
PORT = 8765
_SEAT_LETTER = {WHITE: "W", BLACK: "B"}


def _prompt_login(client: NetworkGameClient) -> dict:
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    return client.login(username, password)


# Returns the seated color (WHITE/BLACK) for matchmaking or joining a room
# as its opponent, or None for joining a room as a spectator - main() below
# is what turns that None into "skip building a NetworkController at all"
# (see is_spectator there). Loops on any rejection/timeout rather than
# giving up outright, the same "try again" UX play() already had.
def _prompt_for_game(client: NetworkGameClient) -> Optional[str]:
    print("Type 'play' for matchmaking, 'create' to open a room, or 'join <id>' to join one.")
    while True:
        typed = input("> ").strip()
        lowered = typed.lower()

        if lowered == "play":
            play_ack = client.play()
            if not play_ack["accepted"]:
                print(f"Could not queue: {play_ack['reason']}")
                continue

            print("Searching for an opponent...")
            try:
                seat_message = client.wait_for_seat()
            except MatchmakingTimeoutError:
                # The server itself gave up (see server/matchmaking.py's
                # TIMEOUT_MS) - reported the moment it happens, not after
                # our own longer local wait_for_seat timeout also elapses.
                print("No opponent found in time - try again.")
                continue
            except NetworkClientError:
                print("Lost connection while waiting for a match.")
                continue
            return seat_message["color"]

        if lowered == "create":
            create_ack = client.create_room()
            if not create_ack["accepted"]:
                print(f"Could not create a room: {create_ack['reason']}")
                continue

            room_id = create_ack["room_id"]
            print(f"Room created: {room_id} - share this id with your opponent. Waiting for them to join...")
            try:
                # No fixed timeout on the wire for this (unlike PLAY's own
                # matchmaking_timeout) - a room just waits until its
                # creator cancels it themselves (Ctrl+C) or someone joins.
                # A day-long timeout stands in for "indefinitely" - Queue.get
                # needs an actual float, and float("inf") isn't a timeout
                # value the underlying lock primitives are guaranteed to
                # accept cleanly.
                seat_message = client.wait_for_seat(timeout=86_400.0)
            except NetworkClientError:
                print("Lost connection while waiting for an opponent.")
                continue
            return seat_message["color"]

        if lowered.startswith("join "):
            room_id = typed[len("join "):].strip()
            if not room_id:
                print("(usage: 'join <room id>')")
                continue

            join_ack = client.join_room(room_id)
            if not join_ack["accepted"]:
                print(f"Could not join room {room_id}: {join_ack['reason']}")
                continue

            if join_ack["role"] == "spectator":
                print(f"Joined room {room_id} as a spectator.")
                return None

            print(f"Joined room {room_id} as the opponent.")
            try:
                seat_message = client.wait_for_seat()
            except NetworkClientError:
                print("Lost connection while waiting to be seated.")
                continue
            return seat_message["color"]

        print("(type 'play', 'create', or 'join <id>')")


def _wait_for_first_snapshot(client: NetworkGameClient, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in client.poll_messages():
            if "pieces" in message:
                return message
        time.sleep(0.01)
    raise NetworkClientError("timed out waiting for the first board snapshot")


def main() -> None:  # pragma: no cover
    client = NetworkGameClient(HOST, PORT)

    login_ack = _prompt_login(client)
    if not login_ack["accepted"]:
        print(f"Login failed: {login_ack['reason']}")
        return
    print(f"Logged in as {login_ack['username']} (rating {login_ack['rating']})")

    if login_ack.get("reconnected"):
        my_color = login_ack["color"]
        print(f"Reconnected to your game as {my_color}")
    else:
        my_color = _prompt_for_game(client)
        print(f"Seated as {my_color}" if my_color is not None else "Spectating.")

    # A spectator (see server/rooms.py) has no seat of their own to move as
    # - every click/jump handler below becomes a no-op, and no
    # NetworkController is even built, rather than one that would just
    # reject everything a real seated player's could legitimately do.
    is_spectator = my_color is None

    state = GameViewState(_wait_for_first_snapshot(client))

    cell_size = compute_cell_size(state.snapshot.board_width, state.snapshot.board_height, screen_size=screen_resolution_px)
    side_panel_width_px = side_panel_width_for(cell_size)
    board_mapper = BoardMapper(
        width=state.snapshot.board_width,
        height=state.snapshot.board_height,
        cell_size=cell_size,
        board_offset_x=side_panel_width_px,
    )
    canvas = ImgCanvas(
        board_width=state.snapshot.board_width,
        board_height=state.snapshot.board_height,
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
        skin=piece_config.DEFAULT_SKIN,
    )
    renderer = Renderer(
        canvas,
        player_names={WHITE: "White", BLACK: "Black"},
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
    )

    controller = None if is_spectator else NetworkController(my_color)
    my_letter = None if is_spectator else _SEAT_LETTER[my_color]

    def handle_click(x: int, y: int) -> None:
        if controller is None:
            return
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.click(cell, state.snapshot)
        if isinstance(request, MoveRequest):
            source = square_name(request.source, state.snapshot.board_height)
            destination = square_name(request.destination, state.snapshot.board_height)
            client.send_command(f"{my_letter}{source}{destination}")

    def handle_jump(x: int, y: int) -> None:
        if controller is None:
            return
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.jump(cell)
        if isinstance(request, JumpRequest):
            square = square_name(request.position, state.snapshot.board_height)
            client.send_command(f"{my_letter}J{square}")

    window = GameWindow("KFChess (online)")
    window.on_click(handle_click)
    window.on_jump(handle_jump)

    running = True
    while running:
        state.begin_batch()
        for message in client.poll_messages():
            state.apply_message(message)
        state.end_batch()

        # controller.selected is purely this client's own UX state - the
        # server's own broadcast has no notion of it (see
        # client/network_controller.py) - so it's overlaid here just for
        # rendering the highlight, the same role GameEngine.snapshot's own
        # selected argument plays for the local GUI (see app.py's App.render).
        # None for a spectator, who has no controller (and thus nothing of
        # their own ever selected) at all.
        selected_cell = controller.selected if controller is not None else None
        display_snapshot = dataclasses.replace(state.snapshot, selected_cell=selected_cell)
        ui_snapshot = build_ui_snapshot(
            display_snapshot, move_log=state.panel_state, score=state.panel_state, status_message=state.status_message
        )
        canvas.begin_frame()
        renderer.draw(ui_snapshot)
        running = window.show(canvas.frame())
        time.sleep(0.01)

    window.close()
    client.close()


if __name__ == "__main__":  # pragma: no cover
    main()
