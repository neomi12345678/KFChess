from server.matchmaking import RATING_RANGE, TIMEOUT_MS, MatchmakingQueue


def test_find_match_is_none_when_fewer_than_two_are_waiting():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)

    assert queue.find_match() is None


def test_find_match_pairs_two_within_rating_range():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)
    queue.enqueue("bob", 1200 + RATING_RANGE)

    assert queue.find_match() == ("alice", "bob")


def test_find_match_returns_none_when_out_of_rating_range():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)
    queue.enqueue("bob", 1200 + RATING_RANGE + 1)

    assert queue.find_match() is None


def test_find_match_returns_the_earliest_queued_pair_first():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)
    queue.enqueue("carol", 1205)
    queue.enqueue("bob", 1200)

    # alice queued before bob, and both carol/bob are in range of alice -
    # the earliest-queued compatible pair wins, not just any compatible pair.
    assert queue.find_match() == ("alice", "carol")


def test_remove_takes_a_username_out_of_the_queue():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)

    queue.remove("alice")

    assert queue.is_waiting("alice") is False


def test_remove_of_an_absent_username_is_a_no_op():
    queue = MatchmakingQueue()

    queue.remove("nobody")  # must not raise

    assert queue.is_waiting("nobody") is False


def test_is_waiting_reflects_queue_membership():
    queue = MatchmakingQueue()

    assert queue.is_waiting("alice") is False

    queue.enqueue("alice", 1200)

    assert queue.is_waiting("alice") is True


def test_advance_time_returns_nothing_before_the_timeout():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)

    expired = queue.advance_time(TIMEOUT_MS - 1)

    assert expired == []
    assert queue.is_waiting("alice") is True


def test_advance_time_expires_and_removes_once_the_timeout_is_reached():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)

    expired = queue.advance_time(TIMEOUT_MS)

    assert expired == ["alice"]
    assert queue.is_waiting("alice") is False


def test_advance_time_accumulates_across_multiple_calls():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)

    queue.advance_time(TIMEOUT_MS - 100)
    expired = queue.advance_time(100)

    assert expired == ["alice"]


def test_advance_time_honors_a_custom_timeout_ms():
    queue = MatchmakingQueue(timeout_ms=100)
    queue.enqueue("alice", 1200)

    assert queue.advance_time(99) == []
    assert queue.advance_time(1) == ["alice"]


def test_advance_time_only_expires_whoever_actually_crossed_the_timeout():
    queue = MatchmakingQueue()
    queue.enqueue("alice", 1200)
    queue.advance_time(TIMEOUT_MS - 100)  # alice is nearly expired
    queue.enqueue("bob", 1200)  # bob just joined, far from expiring

    expired = queue.advance_time(100)

    assert expired == ["alice"]
    assert queue.is_waiting("bob") is True
