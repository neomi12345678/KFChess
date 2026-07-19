"""Networked counterpart to play.py: same graphical window/renderer, but
driven by the server (see server/ws_server.py) over WebSocket instead of a
local GameEngine. Login/matchmaking happen in the terminal before the
window opens (the Home screen's own "shell, not GUI" login step - see
server/client_cli.py, the text-only equivalent of this); once matched,
this renders whatever server/protocol.py's snapshot broadcasts say the
board looks like, and turns clicks into wire commands via
server/network_controller.py instead of a local Controller.

No move-log/score side panels yet - those need a discrete event stream
(see events/observers.py), and the wire protocol here only ever sends
whole-board snapshots, not individual events (see server/protocol.py's
snapshot_to_json).

Run: python play_online.py
"""

import dataclasses
import getpass
import time

import piece_config
from boardio.algebraic_notation import square_name
from display_config import compute_cell_size, screen_resolution_px
from input.board_mapper import BoardMapper
from model.piece import BLACK, WHITE
from server.network_client import NetworkClientError, NetworkGameClient
from server.network_controller import JumpRequest, MoveRequest, NetworkController
from server.protocol import snapshot_from_json
from view.canvas.img_canvas import ImgCanvas
from view.canvas.window import GameWindow
from view.renderer import Renderer

HOST = "localhost"
PORT = 8765
_SEAT_LETTER = {WHITE: "W", BLACK: "B"}


def _prompt_login(client: NetworkGameClient) -> dict:
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    return client.login(username, password)


def _prompt_and_find_match(client: NetworkGameClient) -> str:
    print("Type 'play' to find a match.")
    while True:
        typed = input("> ").strip().lower()
        if typed != "play":
            print("(type 'play' to search for a match)")
            continue

        play_ack = client.play()
        if not play_ack["accepted"]:
            print(f"Could not queue: {play_ack['reason']}")
            continue

        print("Searching for an opponent...")
        try:
            seat_message = client.wait_for_seat()
        except NetworkClientError:
            print("Could not find a match in time.")
            continue
        return seat_message["color"]


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
        my_color = _prompt_and_find_match(client)
        print(f"Seated as {my_color}")

    first_snapshot_payload = _wait_for_first_snapshot(client)
    latest_snapshot = snapshot_from_json(first_snapshot_payload)

    cell_size = compute_cell_size(latest_snapshot.board_width, latest_snapshot.board_height, screen_size=screen_resolution_px)
    board_mapper = BoardMapper(width=latest_snapshot.board_width, height=latest_snapshot.board_height, cell_size=cell_size)
    canvas = ImgCanvas(
        board_width=latest_snapshot.board_width,
        board_height=latest_snapshot.board_height,
        side_panel_width_px=0,
        cell_size=cell_size,
        skin=piece_config.DEFAULT_SKIN,
    )
    renderer = Renderer(canvas, player_names={WHITE: "White", BLACK: "Black"}, cell_size=cell_size)

    controller = NetworkController(my_color)
    my_letter = _SEAT_LETTER[my_color]

    def handle_click(x: int, y: int) -> None:
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.click(cell, latest_snapshot)
        if isinstance(request, MoveRequest):
            source = square_name(request.source, latest_snapshot.board_height)
            destination = square_name(request.destination, latest_snapshot.board_height)
            client.send_command(f"{my_letter}{source}{destination}")

    def handle_jump(x: int, y: int) -> None:
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.jump(cell)
        if isinstance(request, JumpRequest):
            square = square_name(request.position, latest_snapshot.board_height)
            client.send_command(f"{my_letter}J{square}")

    window = GameWindow("KFChess (online)")
    window.on_click(handle_click)
    window.on_jump(handle_jump)

    disconnect_countdown_text = None

    running = True
    while running:
        saw_snapshot_this_batch = False
        saw_countdown_this_batch = False
        for message in client.poll_messages():
            if "pieces" in message:
                latest_snapshot = snapshot_from_json(message)
                saw_snapshot_this_batch = True
            elif message.get("type") == "game_over":
                print(f"Game over. New ratings: {message['ratings']}")
            elif message.get("type") == "disconnect_countdown":
                disconnect_countdown_text = (
                    f"Opponent disconnected - resigning in {message['seconds_remaining']}s unless they return"
                )
                saw_countdown_this_batch = True

        # A tick that broadcast a snapshot but no accompanying
        # disconnect_countdown means the opponent's seat is no longer
        # disconnected (see server/ws_server.py's _advance_current_game,
        # which only ever sends the countdown while is_disconnected(seat))
        # - clear the stale banner rather than leaving last tick's message
        # on screen forever once they reconnect.
        if saw_snapshot_this_batch and not saw_countdown_this_batch:
            disconnect_countdown_text = None

        # controller.selected is purely this client's own UX state - the
        # server's own broadcast has no notion of it (see
        # server/network_controller.py) - so it's overlaid here just for
        # rendering the highlight, the same role GameEngine.snapshot's own
        # selected argument plays for the local GUI (see app.py's App.render).
        display_snapshot = dataclasses.replace(latest_snapshot, selected_cell=controller.selected)
        canvas.begin_frame()
        renderer.draw(display_snapshot, status_message=disconnect_countdown_text)
        running = window.show(canvas.frame())
        time.sleep(0.01)

    window.close()
    client.close()


if __name__ == "__main__":  # pragma: no cover
    main()
