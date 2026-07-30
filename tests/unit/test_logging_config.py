"""server/logging_config.py's own JsonFormatter and correlation contextvars -
the Server_Design.md §9 "structured logs, correlated by room_id/user_id"
requirement. Exercises format() directly against a real logging.LogRecord
(the same object logging itself constructs), not a mock - contextvars are
set/reset per test via .set()'s own returned Token so one test's context
never leaks into the next.
"""

import json
import logging

from server.logging_config import JsonFormatter, room_id_ctx, username_ctx


def _make_record(message: str = "hello", exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=exc_info,
    )


def test_a_plain_log_record_has_no_username_or_room_id_by_default():
    payload = json.loads(JsonFormatter().format(_make_record("plain message")))

    assert payload["message"] == "plain message"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert "username" not in payload
    assert "room_id" not in payload


def test_username_ctx_is_included_once_set():
    token = username_ctx.set("alice")
    try:
        payload = json.loads(JsonFormatter().format(_make_record()))
    finally:
        username_ctx.reset(token)

    assert payload["username"] == "alice"


def test_room_id_ctx_is_included_once_set():
    token = room_id_ctx.set("room-123")
    try:
        payload = json.loads(JsonFormatter().format(_make_record()))
    finally:
        room_id_ctx.reset(token)

    assert payload["room_id"] == "room-123"


def test_both_username_and_room_id_can_be_set_together():
    username_token = username_ctx.set("bob")
    room_token = room_id_ctx.set("room-456")
    try:
        payload = json.loads(JsonFormatter().format(_make_record()))
    finally:
        username_ctx.reset(username_token)
        room_id_ctx.reset(room_token)

    assert payload["username"] == "bob"
    assert payload["room_id"] == "room-456"


def test_resetting_the_context_stops_future_records_from_carrying_it():
    token = username_ctx.set("carol")
    username_ctx.reset(token)

    payload = json.loads(JsonFormatter().format(_make_record()))

    assert "username" not in payload


def test_exception_info_is_included_as_a_real_traceback():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = _make_record("it crashed", exc_info=sys.exc_info())

    payload = json.loads(JsonFormatter().format(record))

    assert "RuntimeError: boom" in payload["exception"]
