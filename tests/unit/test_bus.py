from events.bus import Bus


def test_publish_calls_the_subscribed_handler_with_the_event():
    bus = Bus()
    received = []
    bus.subscribe(str, received.append)

    bus.publish("the-event")

    assert received == ["the-event"]


def test_publish_calls_every_subscriber_in_subscription_order():
    bus = Bus()
    calls = []
    bus.subscribe(str, lambda event: calls.append(("first", event)))
    bus.subscribe(str, lambda event: calls.append(("second", event)))

    bus.publish("the-event")

    assert calls == [("first", "the-event"), ("second", "the-event")]


def test_publish_of_a_type_with_no_subscribers_does_not_raise():
    bus = Bus()

    bus.publish("nobody-listening")  # must not raise


def test_publish_only_reaches_subscribers_of_that_exact_event_type():
    bus = Bus()
    str_events = []
    int_events = []
    bus.subscribe(str, str_events.append)
    bus.subscribe(int, int_events.append)

    bus.publish("for-str")

    assert str_events == ["for-str"]
    assert int_events == []
