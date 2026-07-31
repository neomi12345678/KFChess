"""Single place every service dials its own NATS connection from.

Before this module, `import nats` plus a bare `nats.connect(nats_url)` was
written independently in seven places - server/main.py, this package's own
lifecycle.py, and five services/*/main.py - always with the exact same
one-argument call. Collecting it here means a project-wide connection
option (retry/reconnect policy, TLS, an error callback) only ever needs to
change in one place instead of seven, the same problem server/nats/events.py's
own docstring already solved for hand-built publish/subscribe payloads.

`nats` (nats-py) is still only ever imported lazily, inside connect() -
importing this module (a plain async function) does not pull in the
dependency, so a bare-metal deployment that never sets NATS_URL (see
server/main.py's own _build_matchmaking_relay) still never needs it
installed.
"""


async def connect(nats_url: str):
    import nats

    return await nats.connect(nats_url)
