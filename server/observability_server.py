"""Shared health/readiness/metrics HTTP surface - Server_Design.md §9's own
health/readiness probes and metrics requirements, the two Observability
pillars this pass adds (structured logging, the third, already landed
separately - see server/logging_config.py).

One HTTP server per service (services/api_gateway/main.py is the one
exception - already aiohttp, adds these as ordinary routes on its own
existing app instead of a second server here - see its own docstring)
built on wsgiref.simple_server (stdlib - no new dependency for the
transport itself, only prometheus_client is new) running in a daemon
thread, so a synchronous WSGI app can sit alongside each service's own
asyncio event loop without needing an async HTTP framework as a new
dependency for five services that don't otherwise need one.

    GET /healthz  - liveness: always 200 if this process can accept a TCP
                    connection and run Python at all. A hung/deadlocked
                    asyncio event loop wouldn't even get this far - that's
                    the whole liveness signal Kubernetes needs (see §9's own
                    "quickly enough to detect a crashed/hung pod").
    GET /readyz   - readiness: runs every check in the readiness_checks dict
                    this service was given (its own actual dependencies -
                    Redis/NATS/Postgres, whichever it holds), synchronously.
                    200 only if every one passes; 503 with a JSON body
                    naming which failed otherwise.
    GET /metrics  - prometheus_client's own default registry, in Prometheus
                    text exposition format - every Counter/Gauge/Histogram
                    each service registers at module scope shows up here
                    automatically; nothing to wire per-metric here.

Readiness checks are deliberately synchronous callables, not coroutines -
this server runs on a plain background thread, not the asyncio event loop,
so there's nothing to await here anyway. Consistent with this project's own
server/redis/*'s already-synchronous Redis clients (see their own
docstrings on why a plain sync client is the right call); a NATS check
reads Client.is_connected (a real, plain, thread-safe boolean property -
verified via inspect, not guessed) rather than awaiting anything. Every
caller's own readiness check still needs its own short connect/socket
timeout (redis-py's default is *no* timeout at all) - a genuinely
unreachable dependency must fail /readyz fast, not hang it, something a
real docker-compose run (Redis stopped mid-check) is what actually
surfaced, not a guess.

serve_forever runs on a ThreadingMixIn'd WSGIServer, not the plain
single-threaded default - plain wsgiref.simple_server handles one request
at a time, so a slow/hanging /readyz check (see above) would otherwise
also block /healthz on the very same server from answering at all, which
would turn a *readiness* problem into a false *liveness* failure (a pod
restart doesn't fix an unreachable Redis).
"""

import json
import logging
import threading
from socketserver import ThreadingMixIn
from typing import Callable, Dict
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from prometheus_client import make_wsgi_app

_logger = logging.getLogger(__name__)

ReadinessChecks = Dict[str, Callable[[], bool]]


# Every log line elsewhere in this project goes through
# server/logging_config.py's own JSON formatter - wsgiref's own default
# per-request logging writes raw, unformatted lines straight to stderr
# instead, which would both be noisy (a Kubernetes probe hits /healthz and
# /readyz every few seconds) and break JSON log aggregation. Silenced, not
# rerouted through _logger: there's nothing about "somebody GET'd /healthz"
# worth keeping.
class _QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


# See this module's own docstring on why threaded, not wsgiref's plain
# single-request-at-a-time default.
class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _run_readiness_checks(checks: ReadinessChecks) -> Dict[str, bool]:
    results = {}
    for name, check in checks.items():
        try:
            results[name] = bool(check())
        except Exception:
            _logger.exception("readiness check '%s' raised", name)
            results[name] = False
    return results


def _build_app(readiness_checks: ReadinessChecks):
    metrics_app = make_wsgi_app()

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")

        if path == "/healthz":
            start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"ok"]

        if path == "/readyz":
            results = _run_readiness_checks(readiness_checks)
            body = json.dumps(results).encode("utf-8")
            status = "200 OK" if all(results.values()) else "503 Service Unavailable"
            start_response(status, [("Content-Type", "application/json")])
            return [body]

        return metrics_app(environ, start_response)

    return app


# Runs forever on a daemon thread - never joined, dies with the process
# (matching every other background task in this project that has nothing
# to gracefully shut down for, e.g. server/main.py's own
# _run_shard_heartbeat). A real thread, not a second asyncio task:
# wsgiref.simple_server is a blocking, synchronous server - see this
# module's own docstring on why that's the right trade-off here rather
# than an async HTTP framework.
def start_observability_server(port: int, readiness_checks: ReadinessChecks) -> None:
    app = _build_app(readiness_checks)
    server = make_server(
        "0.0.0.0", port, app, server_class=_ThreadingWSGIServer, handler_class=_QuietWSGIRequestHandler
    )
    thread = threading.Thread(target=server.serve_forever, name="observability-server", daemon=True)
    thread.start()
    _logger.info("observability server (health/ready/metrics) listening on 0.0.0.0:%s", port)
