"""Networked counterpart to play.py: same graphical window/renderer, but
driven by the server (see server/ws_server.py) over WebSocket instead of a
local GameEngine. Login and matchmaking/room setup happen in a small tkinter
GUI window before the game window opens (see client/setup_dialogs.py - cv2,
which the game window itself is built on, has no text-entry/button widgets
of its own; client/client_cli.py remains the separate, terminal-only shell
client the Home screen's own "shell, not GUI" login step uses); once
seated, this renders whatever net_protocol.py's snapshot broadcasts say
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
main() here is only ever responsible for the login/matchmaking setup step,
wiring GameViewState up to a real NetworkGameClient/GameWindow, and driving
the render loop - never for deciding what any wire message means.

Run: python play_online.py
"""

import dataclasses
import time

import piece_config
from boardio.algebraic_notation import square_name
from client.game_view_state import GameViewState
from client.network_client import NetworkClientError, NetworkGameClient
from client.network_controller import JumpRequest, MoveRequest, NetworkController
from client.setup_dialogs import SetupCancelled, run_game_setup, run_login
from display_config import compute_cell_size, screen_resolution_px, side_panel_width_for
from events.game_events import GameEndedEvent
from input.board_mapper import BoardMapper
from model.piece import BLACK, WHITE
from net_protocol import HOST, PORT, build_jump, build_move
from view.canvas.img_canvas import ImgCanvas
from view.canvas.window import GameWindow
from view.renderer import Renderer
from view.ui_snapshot import build_ui_snapshot


def _print_ratings_if_game_over(event: GameEndedEvent) -> None:
    if event.new_ratings is not None:
        print(f"Game over. New ratings: {event.new_ratings}")


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

    try:
        # run_login only ever returns once the server has accepted the
        # login (it loops the GUI form on rejection itself) - see
        # client/setup_dialogs.py.
        login_ack = run_login(client)
        print(f"Logged in as {login_ack['username']} (rating {login_ack['rating']})")

        if login_ack.get("reconnected"):
            my_color = login_ack["color"]
            print(f"Reconnected to your game as {my_color}")
        elif login_ack.get("resuming_room_id"):
            # A room this account was already in survived a server restart
            # (see server/rooms.py's RoomStore) - wait for the other player
            # to reconnect too rather than showing the create/join dialog
            # again (see server/ws_server.py's _handle_login for the
            # server-side half of this).
            print(f"Resuming room {login_ack['resuming_room_id']} - waiting for the other player...")
            my_color = client.wait_for_seat(timeout=86_400.0)["color"]
            print(f"Resumed as {my_color}")
        else:
            my_color = run_game_setup(client)
            print(f"Seated as {my_color}" if my_color is not None else "Spectating.")
    except SetupCancelled:
        client.close()
        return

    # A spectator (see server/rooms.py) has no seat of their own to move as
    # - every click/jump handler below becomes a no-op, and no
    # NetworkController is even built, rather than one that would just
    # reject everything a real seated player's could legitimately do.
    is_spectator = my_color is None

    state = GameViewState(_wait_for_first_snapshot(client))
    state.bus.subscribe(GameEndedEvent, _print_ratings_if_game_over)

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
    # {color: real username} for whichever colors the server's first
    # snapshot actually named (see server/ws_server.py's _names_for and
    # net_protocol.py's PanelState.name_for) - never a "White"/"Black"
    # placeholder. A color PanelState has no name for (there shouldn't be
    # one in practice; every networked GameSession names both seats up
    # front) is simply left out, so Renderer draws that side's card with no
    # name line at all instead of a guess (see view/renderer.py's own
    # comment on player_names defaulting to empty).
    player_names = {
        color: name
        for color in (WHITE, BLACK)
        if (name := state.panel_state.name_for(color)) is not None
    }
    renderer = Renderer(
        canvas,
        player_names=player_names,
        side_panel_width_px=side_panel_width_px,
        cell_size=cell_size,
    )

    controller = None if is_spectator else NetworkController(my_color)

    def handle_click(x: int, y: int) -> None:
        if controller is None:
            return
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.click(cell, state.snapshot)
        if isinstance(request, MoveRequest):
            source = square_name(request.source, state.snapshot.board_height)
            destination = square_name(request.destination, state.snapshot.board_height)
            client.send_command(build_move(my_color, source, destination))

    def handle_jump(x: int, y: int) -> None:
        if controller is None:
            return
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.jump(cell)
        if isinstance(request, JumpRequest):
            square = square_name(request.position, state.snapshot.board_height)
            client.send_command(build_jump(my_color, square))

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
