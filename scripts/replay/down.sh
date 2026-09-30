#!/bin/bash
# Remove only the replay containers, volume and network (healdb-replay-*). Outputs under hab-data are kept.
set -u
docker rm -f healdb-replay-py healdb-replay-mysql >/dev/null 2>&1 || true
docker volume rm healdb-replay-mysql-data >/dev/null 2>&1 || true
docker network rm healdb-replay-net >/dev/null 2>&1 || true
echo "removed healdb-replay-* containers, volume and network"
