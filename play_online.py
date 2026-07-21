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

The moves-log/score side panels are driven by server/protocol.py's
PanelState - a client-side duck-typed stand-in for events/observers.py's
MoveLogObserver/ScoreObserver, rebuilt from each broadcast's own
"move_log"/"score" keys (see server/session.py, which registers the real
observers on the server's own GameEngine) rather than from a live local
event stream, since only the server ever sees GameEngine's raw events.

Sound/animation cues go through the exact same events/sound.py's SoundCues
and events/game_animations.py's GameAnimationCues game_builder.py wires up
for local play (see build_app there) - just fed by a local Bus of this
client's own instead of a live GameEngine. There's no GameEngine here to
publish MoveLoggedEvent/ArrivalEvent itself (unlike play.py), so
_publish_move_events below re-derives those two events from each newly
arrived move-log entry's own notation string - "x" for a capture, a
trailing "^" for a jump (see boardio/algebraic_notation.py's own
move_notation/jump_notation) - and publishes them on this client's Bus,
same as GameEngine's own BusBridge would. The fields neither SoundCues nor
GameAnimationCues ever reads (piece identity, board positions, the real
captured Piece) are left as placeholders - the wire never carries them, and
nothing downstream looks at them.

Run: python play_online.py
"""

import dataclasses
import getpass
import time
from typing import Dict, Optional

import piece_config
from boardio.algebraic_notation import square_name
from client.network_client import MatchmakingTimeoutError, NetworkClientError, NetworkGameClient
from client.network_controller import JumpRequest, MoveRequest, NetworkController
from display_config import compute_cell_size, screen_resolution_px, side_panel_width_for
from events.bus import Bus
from events.game_animations import GameAnimationCues
from events.game_events import GameEndedEvent, GameStartedEvent
from events.sound import SoundCues
from input.board_mapper import BoardMapper
from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, WHITE
from server.protocol import PanelState, snapshot_from_json
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


# A stand-in for the real captured Piece SoundCues/GameAnimationCues never
# actually get here (see this module's own docstring) - ArrivalEvent's
# captured_piece is only ever tested for "is this None or not" by either
# subscriber, never read into, so any non-None object satisfies that check.
_CAPTURED_PIECE_PLACEHOLDER = object()


# Diffs panel_state's own per-color move-log entry counts against
# move_log_counts (this client's running tally, updated in place) and
# publishes a MoveLoggedEvent - plus an ArrivalEvent for a capture - on bus
# for every entry that's newly arrived since the last call, deriving
# is_capture/is_jump from the entry's own notation string the same way the
# server's real algebraic-notation grammar produced it. Ordinarily at most
# one new entry per color per broadcast, but this holds up fine even if a
# client fell behind a tick and a broadcast's move log grew by more than one
# entry at once.
def _publish_move_events(bus: Bus, panel_state: PanelState, move_log_counts: Dict[str, int]) -> None:
    for color in (WHITE, BLACK):
        entries = panel_state.entries_for(color)
        previous_count = move_log_counts.get(color, 0)
        for entry in entries[previous_count:]:
            is_jump = entry.notation.endswith("^")
            is_capture = "x" in entry.notation
            bus.publish(
                MoveLoggedEvent(
                    color=color,
                    kind="",
                    source=None,
                    destination=None,
                    is_capture=is_capture,
                    is_jump=is_jump,
                    elapsed_ms=entry.elapsed_ms,
                    piece_id="",
                )
            )
            if is_capture:
                bus.publish(ArrivalEvent(piece=None, captured_piece=_CAPTURED_PIECE_PLACEHOLDER))
        move_log_counts[color] = len(entries)


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

    first_snapshot_payload = _wait_for_first_snapshot(client)
    latest_snapshot = snapshot_from_json(first_snapshot_payload)
    panel_state = PanelState()
    panel_state.update_from_json(first_snapshot_payload)

    # Seeded from the first snapshot's own counts, not empty - a
    # mid-game reconnect's move log can already be several entries deep,
    # and none of those already-happened moves should each play a sound
    # cue the instant this client catches up to them.
    move_log_counts: Dict[str, int] = {color: len(panel_state.entries_for(color)) for color in (WHITE, BLACK)}

    # This client's own local Bus - the network counterpart to
    # game_builder.py's build_app wiring the same two subscribers to a
    # GameEngine-fed Bus for local play (see this module's own docstring).
    client_bus = Bus()
    SoundCues(client_bus)
    GameAnimationCues(client_bus)
    client_bus.publish(GameStartedEvent())

    cell_size = compute_cell_size(latest_snapshot.board_width, latest_snapshot.board_height, screen_size=screen_resolution_px)
    side_panel_width_px = side_panel_width_for(cell_size)
    board_mapper = BoardMapper(
        width=latest_snapshot.board_width,
        height=latest_snapshot.board_height,
        cell_size=cell_size,
        board_offset_x=side_panel_width_px,
    )
    canvas = ImgCanvas(
        board_width=latest_snapshot.board_width,
        board_height=latest_snapshot.board_height,
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
        request = controller.click(cell, latest_snapshot)
        if isinstance(request, MoveRequest):
            source = square_name(request.source, latest_snapshot.board_height)
            destination = square_name(request.destination, latest_snapshot.board_height)
            client.send_command(f"{my_letter}{source}{destination}")

    def handle_jump(x: int, y: int) -> None:
        if controller is None:
            return
        cell = board_mapper.pixel_to_cell(x, y)
        request = controller.jump(cell)
        if isinstance(request, JumpRequest):
            square = square_name(request.position, latest_snapshot.board_height)
            client.send_command(f"{my_letter}J{square}")

    window = GameWindow("KFChess (online)")
    window.on_click(handle_click)
    window.on_jump(handle_jump)

    # How long a rejected move/jump's message stays on screen - the ack
    # itself (unlike disconnect_countdown) is a one-off reply, not a
    # standing state the server keeps re-broadcasting, so there's no
    # "still true" signal to clear it on; it just times out instead.
    ILLEGAL_MOVE_MESSAGE_S = 2.0

    disconnect_countdown_text = None
    illegal_move_text = None
    illegal_move_expires_at = 0.0

    running = True
    while running:
        saw_snapshot_this_batch = False
        saw_countdown_this_batch = False
        for message in client.poll_messages():
            if "pieces" in message:
                latest_snapshot = snapshot_from_json(message)
                panel_state.update_from_json(message)
                saw_snapshot_this_batch = True
                _publish_move_events(client_bus, panel_state, move_log_counts)
            elif message.get("type") == "game_over":
                print(f"Game over. New ratings: {message['ratings']}")
                # arrival=None - unlike every other GameEndedEvent, there's
                # no ArrivalEvent behind a networked game-over at all (see
                # server/session.py's resign(), a disconnect timeout rather
                # than a king-capture ArrivalEvent), and neither SoundCues
                # nor GameAnimationCues ever reads this field anyway (see
                # this module's own docstring).
                client_bus.publish(GameEndedEvent(arrival=None))
            elif message.get("type") == "disconnect_countdown":
                disconnect_countdown_text = (
                    f"Opponent disconnected - resigning in {message['seconds_remaining']}s unless they return"
                )
                saw_countdown_this_batch = True
            elif message.get("type") == "ack" and not message.get("accepted"):
                illegal_move_text = f"Illegal move: {message.get('reason')}"
                illegal_move_expires_at = time.monotonic() + ILLEGAL_MOVE_MESSAGE_S

        # A tick that broadcast a snapshot but no accompanying
        # disconnect_countdown means the opponent's seat is no longer
        # disconnected (see server/ws_server.py's _advance_game, which only
        # ever sends the countdown while is_disconnected(seat))
        # - clear the stale banner rather than leaving last tick's message
        # on screen forever once they reconnect.
        if saw_snapshot_this_batch and not saw_countdown_this_batch:
            disconnect_countdown_text = None

        if illegal_move_text is not None and time.monotonic() >= illegal_move_expires_at:
            illegal_move_text = None

        # disconnect_countdown_text wins the single status-message slot when
        # both are live - it reflects a standing fact the opponent is
        # waiting on, not a transient one-off like a rejected move.
        status_message = disconnect_countdown_text or illegal_move_text

        # controller.selected is purely this client's own UX state - the
        # server's own broadcast has no notion of it (see
        # client/network_controller.py) - so it's overlaid here just for
        # rendering the highlight, the same role GameEngine.snapshot's own
        # selected argument plays for the local GUI (see app.py's App.render).
        # None for a spectator, who has no controller (and thus nothing of
        # their own ever selected) at all.
        selected_cell = controller.selected if controller is not None else None
        display_snapshot = dataclasses.replace(latest_snapshot, selected_cell=selected_cell)
        ui_snapshot = build_ui_snapshot(
            display_snapshot, move_log=panel_state, score=panel_state, status_message=status_message
        )
        canvas.begin_frame()
        renderer.draw(ui_snapshot)
        running = window.show(canvas.frame())
        time.sleep(0.01)

    window.close()
    client.close()


if __name__ == "__main__":  # pragma: no cover
    main()
