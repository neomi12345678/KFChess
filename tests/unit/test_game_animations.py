from events.bus import ARRIVAL, GAME_ENDED, GAME_STARTED, MOVE_LOGGED, Bus
from events.game_animations import GAME_END_ANIMATION, GAME_START_ANIMATION, GameAnimationCues


def test_game_started_triggers_the_start_animation():
    bus = Bus()
    animations = GameAnimationCues(bus)

    bus.publish(GAME_STARTED)

    assert animations.triggered == [GAME_START_ANIMATION]


def test_game_ended_triggers_the_end_animation():
    bus = Bus()
    animations = GameAnimationCues(bus)

    bus.publish(GAME_ENDED)

    assert animations.triggered == [GAME_END_ANIMATION]


def test_move_logged_and_arrival_trigger_nothing():
    bus = Bus()
    animations = GameAnimationCues(bus)

    bus.publish(MOVE_LOGGED, "some-event")
    bus.publish(ARRIVAL, "some-event")

    assert animations.triggered == []
