from events.bus import Bus


def test_publish_calls_the_subscribed_handler_with_the_event():
    bus = Bus()
    received = []
    bus.subscribe("topic", received.append)

    bus.publish("topic", "the-event")

    assert received == ["the-event"]


def test_publish_calls_every_subscriber_in_subscription_order():
    bus = Bus()
    calls = []
    bus.subscribe("topic", lambda event: calls.append(("first", event)))
    bus.subscribe("topic", lambda event: calls.append(("second", event)))

    bus.publish("topic", "the-event")

    assert calls == [("first", "the-event"), ("second", "the-event")]


def test_publish_to_a_topic_with_no_subscribers_does_not_raise():
    bus = Bus()

    bus.publish("nobody-listening", "the-event")  # must not raise


def test_publish_only_reaches_subscribers_of_that_exact_topic():
    bus = Bus()
    topic_a_events = []
    topic_b_events = []
    bus.subscribe("a", topic_a_events.append)
    bus.subscribe("b", topic_b_events.append)

    bus.publish("a", "for-a")

    assert topic_a_events == ["for-a"]
    assert topic_b_events == []


def test_publish_with_no_event_defaults_to_none():
    bus = Bus()
    received = []
    bus.subscribe("topic", received.append)

    bus.publish("topic")

    assert received == [None]
