"""server/observability_server.py's own WSGI app - Server_Design.md §9's
health/readiness/metrics HTTP surface. Exercises _build_app directly
against a real WSGI environ/start_response pair (the same protocol any
real WSGI server, including wsgiref.simple_server, calls an app with) - no
actual socket/thread needed; start_observability_server's own thin
threading wrapper has nothing left to test once _build_app itself is
proven correct.
"""

from prometheus_client import Counter

from server.observability_server import _build_app

# Module level, not per-test - prometheus_client's default registry raises
# on a duplicate metric name, and this module only ever executes once per
# process regardless of how many times a test function runs.
_TEST_COUNTER = Counter(
    "kfchess_test_observability_counter", "test-only counter for test_observability_server.py"
)


def _get(app, path: str):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {"PATH_INFO": path, "REQUEST_METHOD": "GET"}
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def test_healthz_is_always_200_even_with_no_readiness_checks_configured():
    app = _build_app({})

    status, _headers, body = _get(app, "/healthz")

    assert status == "200 OK"
    assert body == b"ok"


def test_readyz_is_200_when_every_check_passes():
    app = _build_app({"redis": lambda: True, "nats": lambda: True})

    status, _headers, body = _get(app, "/readyz")

    assert status == "200 OK"
    assert b'"redis": true' in body
    assert b'"nats": true' in body


def test_readyz_is_503_when_any_check_fails():
    app = _build_app({"redis": lambda: True, "nats": lambda: False})

    status, _headers, body = _get(app, "/readyz")

    assert status == "503 Service Unavailable"
    assert b'"nats": false' in body
    assert b'"redis": true' in body


def test_readyz_treats_a_raising_check_as_failed_not_a_crash():
    def _boom():
        raise RuntimeError("connection refused")

    app = _build_app({"postgres": _boom})

    status, _headers, body = _get(app, "/readyz")

    assert status == "503 Service Unavailable"
    assert b'"postgres": false' in body


def test_metrics_serves_the_prometheus_registry():
    _TEST_COUNTER.inc()
    app = _build_app({})

    status, _headers, body = _get(app, "/metrics")

    assert status == "200 OK"
    assert b"kfchess_test_observability_counter" in body
