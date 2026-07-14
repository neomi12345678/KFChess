from model.game_state import ArrivalEvent, MoveLoggedEvent
from model.piece import BLACK, KING, KNIGHT, PAWN, Piece, QUEEN, ROOK, WHITE
from model.position import Position
from view.observers import MoveLogObserver, ScoreObserver


def make_piece(color, kind, row=0, col=0):
    return Piece(id=f"{color}-{kind}-{row}{col}", color=color, kind=kind, cell=Position(row, col))


def make_move_event(color, kind=PAWN, source=Position(1, 1), destination=Position(0, 1), is_capture=False, elapsed_ms=0):
    return MoveLoggedEvent(
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
