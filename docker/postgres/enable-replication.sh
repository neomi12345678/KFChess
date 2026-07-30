#!/bin/sh
# Runs once, automatically, on the primary's *first* boot only (the
# official postgres image executes everything under
# /docker-entrypoint-initdb.d/ exactly once, right after initdb, only when
# PGDATA started out empty - see docker-compose.yml's own mount of this
# script there). Appends a pg_hba.conf rule letting the postgres-replica
# service (see replica-entrypoint.sh, also in this directory) open a
# streaming-replication connection as the same POSTGRES_USER already used
# for ordinary connections - the default rule the base image generates from
# POSTGRES_USER/POSTGRES_PASSWORD only covers ordinary databases, not the
# special "replication" pseudo-database a `pg_basebackup`/streaming
# connection asks for, so without this line the replica's own connection
# is rejected outright.
#
# scram-sha-256, not trust - the same password-based auth every other
# connection to this database already uses (see docker-compose.yml's own
# POSTGRES_PASSWORD), not weakened just because this is docker-compose's
# private network.
set -e

echo "host replication ${POSTGRES_USER} all scram-sha-256" >> "$PGDATA/pg_hba.conf"
