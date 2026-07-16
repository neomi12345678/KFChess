from view.canvas.sprite_frames import SpriteAnimator
from model.piece import CAPTURED, PHASE_IDLE, PHASE_JUMP, PHASE_LONG_REST, PHASE_MOVE, PHASE_SHORT_REST


class FakeClock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_animator():
    clock = FakeClock()
    return SpriteAnimator(clock=clock), clock


def test_sprite_path_maps_idle_state_to_the_idle_folder():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", PHASE_IDLE)

    assert path.parts[-3] == "idle"


def test_sprite_path_maps_moving_state_to_the_move_folder():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", PHASE_MOVE)

    assert path.parts[-3] == "move"


def test_sprite_path_maps_airborne_state_to_the_jump_folder():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", PHASE_JUMP)

    assert path.parts[-3] == "jump"


def test_sprite_path_maps_short_rest_state_to_the_short_rest_folder():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", PHASE_SHORT_REST)

    assert path.parts[-3] == "short_rest"


def test_sprite_path_maps_long_rest_state_to_the_long_rest_folder():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", PHASE_LONG_REST)

    assert path.parts[-3] == "long_rest"


def test_sprite_path_falls_back_to_idle_for_a_state_with_no_animation_folder():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", CAPTURED)

    assert path.parts[-3] == "idle"


def test_frame_starts_at_one_the_instant_a_piece_enters_a_state():
    animator, clock = make_animator()

    path = animator.sprite_path("p1", "KW", PHASE_IDLE)

    assert path.name == "1.png"


def test_frame_advances_as_time_passes_in_a_looping_state():
    # idle: 6 frames_per_sec, is_loop=true, 5 sprites (assets/pieces/KW/states/idle).
    animator, clock = make_animator()
    animator.sprite_path("p1", "KW", PHASE_IDLE)  # frame 1 at t=0

    clock.now = 0.2  # 0.2 * 6fps = 1.2 -> 1 whole frame elapsed

    path = animator.sprite_path("p1", "KW", PHASE_IDLE)

    assert path.name == "2.png"


def test_frame_loops_back_to_one_after_a_full_cycle_in_a_looping_state():
    # 5 frames at 6fps -> one full cycle is 5/6s.
    animator, clock = make_animator()
    animator.sprite_path("p1", "KW", PHASE_IDLE)

    clock.now = 5 / 6 + 0.01

    path = animator.sprite_path("p1", "KW", PHASE_IDLE)

    assert path.name == "1.png"


def test_frame_freezes_on_the_last_frame_for_a_non_looping_state():
    # jump: 8 frames_per_sec, is_loop=false, 5 sprites - it should never wrap
    # around and never run past the last frame once its cycle has elapsed.
    animator, clock = make_animator()
    animator.sprite_path("p1", "KW", PHASE_JUMP)

    clock.now = 10.0  # long past the ~0.625s the 5-frame cycle takes

    path = animator.sprite_path("p1", "KW", PHASE_JUMP)

    assert path.name == "5.png"


def test_frame_resets_to_one_when_the_same_piece_changes_state():
    animator, clock = make_animator()
    animator.sprite_path("p1", "KW", PHASE_IDLE)
    clock.now = 0.5  # well into idle's animation

    path = animator.sprite_path("p1", "KW", PHASE_MOVE)

    assert path.name == "1.png"


def test_each_piece_id_tracks_its_own_animation_clock_independently():
    animator, clock = make_animator()
    animator.sprite_path("piece-a", "KW", PHASE_IDLE)  # enters idle at t=0

    clock.now = 0.2  # 1 frame in for piece-a
    animator.sprite_path("piece-b", "KW", PHASE_IDLE)  # piece-b enters idle now, at t=0.2

    path_a = animator.sprite_path("piece-a", "KW", PHASE_IDLE)
    path_b = animator.sprite_path("piece-b", "KW", PHASE_IDLE)

    assert path_a.name == "2.png"
    assert path_b.name == "1.png"
