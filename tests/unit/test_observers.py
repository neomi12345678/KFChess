from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, KING, KNIGHT, PAWN, Piece, QUEEN, ROOK, WHITE
from model.position import Position
from events.observers import MoveLogObserver, ScoreObserver


def make_piece(color, kind, row=0, col=0):
    return Piece(id=f"{color}-{kind}-{row}{col}", color=color, kind=kind, cell=Position(row, col))


def make_move_event(
    color, kind=PAWN, source=Position(1, 1), destination=Position(0, 1), is_capture=False, elapsed_ms=0,
    piece_id="mover",
):
    return MoveLoggedEvent(
        piece_id=piece_id,
        color=color,
        kind=kind,
        source=source,
        destination=destination,
        is_capture=is_capture,
        is_jump=False,
        elapsed_ms=elapsed_ms,
    )


def test_move_log_observer_keeps_entries_separated_by_color():
    observer = MoveLogObserver(board_height=8)
    observer.on_move_logged(make_move_event(WHITE, source=Position(6, 4), destination=Position(4, 4)))
    observer.on_move_logged(make_move_event(BLACK, source=Position(1, 4), destination=Position(3, 4)))

    assert [entry.notation for entry in observer.entries_for(WHITE)] == ["e4"]
    assert [entry.notation for entry in observer.entries_for(BLACK)] == ["e5"]


def test_move_log_observer_preserves_insertion_order_for_the_same_color():
    observer = MoveLogObserver(board_height=8)
    observer.on_move_logged(make_move_event(WHITE, source=Position(6, 4), destination=Position(4, 4)))
    observer.on_move_logged(make_move_event(WHITE, kind=KNIGHT, source=Position(7, 6), destination=Position(5, 5)))

    assert [entry.notation for entry in observer.entries_for(WHITE)] == ["e4", "Nf3"]


def test_move_log_observer_returns_an_empty_list_for_a_color_with_no_moves_yet():
    observer = MoveLogObserver(board_height=8)

    assert observer.entries_for(WHITE) == []


def test_move_log_observer_builds_a_capture_notation():
    observer = MoveLogObserver(board_height=8)
    observer.on_move_logged(
        make_move_event(WHITE, kind=ROOK, source=Position(4, 4), destination=Position(2, 4), is_capture=True)
    )

    [entry] = observer.entries_for(WHITE)
    assert entry.notation == "Rxe6"


def test_move_log_observer_builds_jump_notation_with_no_destination_travel():
    observer = MoveLogObserver(board_height=8)
    event = MoveLoggedEvent(
        piece_id="king",
        color=WHITE,
        kind=KING,
        source=Position(4, 4),
        destination=Position(4, 4),
        is_capture=False,
        is_jump=True,
        elapsed_ms=0,
    )

    observer.on_move_logged(event)

    [entry] = observer.entries_for(WHITE)
    assert entry.notation == "Ke4^"


def test_move_log_observer_corrects_a_moves_notation_once_it_actually_lands_short_and_captures():
    # A route conflict or a mid-flight interception (see
    # RealTimeArbiter.plan_route/_intercept_motion) can leave a piece
    # landing somewhere other than its originally requested destination,
    # turning a quiet move into a capture - on_move_logged alone can't know
    # that yet (see MoveLoggedEvent's own docstring), only the later
    # on_arrival tells the truth.
    observer = MoveLogObserver(board_height=8)
    mover = make_piece(WHITE, ROOK, row=4, col=0)
    victim = make_piece(BLACK, PAWN, row=4, col=3)

    observer.on_move_logged(
        make_move_event(
            WHITE, kind=ROOK, source=Position(4, 0), destination=Position(4, 5), piece_id=mover.id,
        )
    )
    assert [entry.notation for entry in observer.entries_for(WHITE)] == ["Rf4"]

    mover.cell = Position(4, 3)  # where it actually stopped, not the requested (4, 5)
    observer.on_arrival(ArrivalEvent(piece=mover, captured_piece=victim))

    # Still a single entry - patched in place, not appended a second time.
    [entry] = observer.entries_for(WHITE)
    assert entry.notation == "Rxd4"


def test_move_log_observer_drops_a_pending_moves_entry_if_its_own_piece_is_captured_before_arriving():
    # RealTimeArbiter._resolve_arrival's reversed-capture defense: an
    # airborne piece can survive and capture the very attacker that was
    # mid-flight toward it, so the attacker's own requested move never
    # actually completes - it shouldn't leave a phantom "moved to X" line
    # behind for an action that never happened.
    observer = MoveLogObserver(board_height=8)
    attacker = make_piece(WHITE, ROOK, row=4, col=0)
    defender = make_piece(BLACK, KNIGHT, row=4, col=5)

    observer.on_move_logged(
        make_move_event(
            WHITE, kind=ROOK, source=Position(4, 0), destination=Position(4, 5), piece_id=attacker.id,
        )
    )
    assert len(observer.entries_for(WHITE)) == 1

    observer.on_arrival(ArrivalEvent(piece=defender, captured_piece=attacker))

    assert observer.entries_for(WHITE) == []


def test_move_log_observer_leaves_an_already_resolved_victims_own_entry_alone():
    # The captured piece in a normal (non-reversed) capture already landed
    # and completed its own, separate move earlier - event.captured_piece
    # here is not "still pending" the way the reversed-capture-defense
    # victim above is, so its own already-correct entry must survive.
    observer = MoveLogObserver(board_height=8)
    victim = make_piece(BLACK, PAWN, row=4, col=3)
    observer.on_move_logged(
        make_move_event(
            BLACK, kind=PAWN, source=Position(3, 3), destination=Position(4, 3), piece_id=victim.id,
        )
    )
    observer.on_arrival(ArrivalEvent(piece=victim, captured_piece=None))  # victim's own arrival resolves first
    assert len(observer.entries_for(BLACK)) == 1

    attacker = make_piece(WHITE, ROOK, row=4, col=0)
    observer.on_arrival(ArrivalEvent(piece=attacker, captured_piece=victim))

    assert len(observer.entries_for(BLACK)) == 1


def test_move_log_observer_records_the_events_elapsed_time():
    observer = MoveLogObserver(board_height=8)
    observer.on_move_logged(make_move_event(WHITE, elapsed_ms=4105))

    [entry] = observer.entries_for(WHITE)
    assert entry.elapsed_ms == 4105


def test_score_observer_starts_every_color_at_zero():
    observer = ScoreObserver()

    assert observer.score_for(WHITE) == 0
    assert observer.score_for(BLACK) == 0


def test_score_observer_credits_the_survivor_not_the_captured_piece():
    observer = ScoreObserver()
    attacker = make_piece(WHITE, QUEEN)
    captured = make_piece(BLACK, PAWN)

    observer.on_arrival(ArrivalEvent(piece=attacker, captured_piece=captured))

    assert observer.score_for(WHITE) == 1
    assert observer.score_for(BLACK) == 0


def test_score_observer_accumulates_across_multiple_captures():
    observer = ScoreObserver()
    attacker = make_piece(WHITE, QUEEN)

    observer.on_arrival(ArrivalEvent(piece=attacker, captured_piece=make_piece(BLACK, PAWN)))
    observer.on_arrival(ArrivalEvent(piece=attacker, captured_piece=make_piece(BLACK, KNIGHT)))

    assert observer.score_for(WHITE) == 1 + 3


def test_score_observer_ignores_an_arrival_with_no_capture():
    observer = ScoreObserver()
    mover = make_piece(WHITE, QUEEN)

    observer.on_arrival(ArrivalEvent(piece=mover, captured_piece=None))

    assert observer.score_for(WHITE) == 0
