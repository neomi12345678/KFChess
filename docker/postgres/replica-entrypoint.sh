#!/bin/sh
# Entrypoint for the postgres-replica service (docker-compose.yml) - the
# stock postgres image has no built-in "clone from another instance and
# follow it" mode, so this wraps its own docker-entrypoint.sh with exactly
# that: on first boot (PGDATA still empty - a fresh volume), it clones the
# primary via pg_basebackup with -R, which - PG12+'s own replacement for a
# separately-written recovery.conf - writes both standby.signal and a
# primary_conninfo pointing at the primary straight into
# postgresql.auto.conf as part of the clone itself. Every boot after that
# (PGDATA already populated, standby.signal already on disk) just starts
# postgres normally, which then stays in continuous streaming-recovery
# mode for as long as standby.signal is present - Server_Design.md §5's
# own "PostgreSQL/MySQL, primary + read replicas."
set -e

if [ -z "$(ls -A "$PGDATA" 2>/dev/null)" ]; then
    echo "PGDATA is empty - bootstrapping as a streaming replica of ${PRIMARY_HOST}:${PRIMARY_PORT:-5432}"
    PGPASSWORD="$POSTGRES_PASSWORD" pg_basebackup \
        -h "$PRIMARY_HOST" -p "${PRIMARY_PORT:-5432}" -U "$POSTGRES_USER" \
        -D "$PGDATA" -Fp -Xs -P -R
fi

exec docker-entrypoint.sh postgres
