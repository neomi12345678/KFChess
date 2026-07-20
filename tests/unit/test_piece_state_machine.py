from view.piece_state_machine import PieceAnimationStateMachine


class FakeClock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_enter_reports_zero_elapsed_the_instant_a_piece_id_is_first_seen():
    machine = PieceAnimationStateMachine(clock=FakeClock())

    elapsed = machine.enter("p1", "idle")

    assert elapsed == 0.0


def test_enter_reports_elapsed_time_while_the_phase_stays_the_same():
    clock = FakeClock()
    machine = PieceAnimationStateMachine(clock=clock)
    machine.enter("p1", "idle")

    clock.now = 0.75

    assert machine.enter("p1", "idle") == 0.75


def test_enter_resets_to_zero_when_the_same_piece_changes_phase():
    clock = FakeClock()
    machine = PieceAnimationStateMachine(clock=clock)
    machine.enter("p1", "idle")
    clock.now = 0.75

    elapsed = machine.enter("p1", "move")

    assert elapsed == 0.0


def test_each_piece_id_tracks_its_own_phase_and_clock_independently():
    clock = FakeClock()
    machine = PieceAnimationStateMachine(clock=clock)
    machine.enter("p1", "idle")

    clock.now = 0.2
    machine.enter("p2", "idle")  # p2 enters idle later than p1 did

    assert machine.enter("p1", "idle") == 0.2
    assert machine.enter("p2", "idle") == 0.0


def test_forget_missing_drops_a_piece_id_not_in_the_present_set():
    clock = FakeClock()
    machine = PieceAnimationStateMachine(clock=clock)
    machine.enter("p1", "idle")
    clock.now = 5.0

    machine.forget_missing(present_piece_ids=set())

    # p1 is treated as newly seen again - elapsed resets to 0, not 5.0.
    assert machine.enter("p1", "idle") == 0.0


def test_forget_missing_keeps_a_piece_id_still_in_the_present_set():
    clock = FakeClock()
    machine = PieceAnimationStateMachine(clock=clock)
    machine.enter("p1", "idle")
    clock.now = 5.0

    machine.forget_missing(present_piece_ids={"p1"})

    assert machine.enter("p1", "idle") == 5.0
