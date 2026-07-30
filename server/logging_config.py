"""Structured (JSON) logging shared by every deployable in this project -
the Server_Design.md §9/§11 Observability requirement, quoted in full:
"Structured logs, correlated by room_id/user_id, so a support or anti-cheat
investigation can follow one game across API Gateway -> Matchmaker -> Game
Allocator -> Game Server Shard -> Persistence Worker without grepping five
machines by hand."

Every one of the six roles (services/api_gateway, services/ws_gateway,
services/matchmaker, services/game_allocator, services/persistence_worker,
server/main.py) previously called the exact same
`logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s
%(levelname)s %(message)s")` - free-text, uncorrelated. configure_logging
below replaces that one line, everywhere, with a JSON formatter instead.

Correlation itself is two module-level contextvars.ContextVar, not a
parameter threaded through every function or appended to every log call:
whoever is about to handle one piece of work (a REST request, an IDENTIFY,
one game's own tick, one NATS message) sets username_ctx/room_id_ctx once
at the top of that scope, and every log statement emitted anywhere inside
it - existing or future, this module's own callers never touch their own
_logger.info(...) call sites - picks it up automatically, since JsonFormatter
reads the contextvar at format time, not at the log call site. contextvars
propagate correctly across `await` within the same asyncio Task (and are
copied, not shared, into a new Task via asyncio.create_task) - exactly the
shape every caller here needs: server/game_loop.py's GameLoop.run_forever
ticks every active game sequentially in one Task, so setting room_id_ctx at
the top of each game's own turn and overwriting it for the next is race-free.

game_id is what's actually threaded through room_id_ctx for a PLAY match
(no real room_id exists) - the same one contextvar serves both, since both
are "this game's own identity" as far as correlating log lines goes.
"""

import contextvars
import json
import logging
from typing import Optional

username_ctx: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("username_ctx", default=None)
room_id_ctx: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("room_id_ctx", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        username = username_ctx.get()
        if username is not None:
            payload["username"] = username

        room_id = room_id_ctx.get()
        if room_id is not None:
            payload["room_id"] = room_id

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


# Replaces every deployable's own logging.basicConfig(...) call - same
# level default (INFO), same "one process, one handler" shape, just a
# structured formatter instead of the free-text one every service shared
# before this.
def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler])
