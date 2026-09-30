#!/bin/bash
# Shared settings for the Docker replay scripts (sourced, not executed). The password is read only from the
# environment variable HAB_MYSQL_PASSWORD and reaches containers by variable name (-e NAME), never by value.

MYSQL_IMAGE=mysql:8.0.33
PY_IMAGE=python:3.12-slim
MYSQL_CONNECTOR_PIN=26.7.0  # the version the workspace replay installed (docs/design/inventario_workspace.md)
MYSQL_C=healdb-replay-mysql
PY_C=healdb-replay-py
NET=healdb-replay-net
VOL=healdb-replay-mysql-data
DUMPS=/home/vinicius/healdb-reconstrucao/x
V1_DIR=v1_dump_0711/Dump20250711_Dump_and_Structure
HEALDB_REPO=/home/vinicius/code/HealDB
OUT=/home/vinicius/hab-data/replay
LOGS=$OUT/logs
EXPORT=$OUT/export
CODE=$OUT/code
XVAL=$OUT/xval
SCRIPTS=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

need_password() {
  if [ -z "${HAB_MYSQL_PASSWORD:-}" ]; then
    echo "HAB_MYSQL_PASSWORD is not set; aborting" >&2
    exit 1
  fi
  # names below are passed to docker as -e NAME: the value never appears on a command line
  export MYSQL_ROOT_PASSWORD="$HAB_MYSQL_PASSWORD"
  export MYSQL_PWD="$HAB_MYSQL_PASSWORD"
}

prepare_dirs() {
  mkdir -p "$LOGS" "$EXPORT" "$CODE" "$XVAL"
}

# rec: append the command (no secrets: only variable names are ever passed) to commands.log, then run it
rec() {
  printf '%s\t%s\n' "$(date '+%F %T')" "$*" >> "$LOGS/commands.log"
  "$@"
}

note() {
  printf '%s\t# %s\n' "$(date '+%F %T')" "$*" >> "$LOGS/commands.log"
}

# start_py: python container on the replay network, code and scripts read-only, exports read-write
start_py() {
  rec docker rm -f "$PY_C" >/dev/null 2>&1 || true
  rec docker run -d --name "$PY_C" --network "$NET" --memory=3g \
    -e PYTHONUNBUFFERED=1 -e PYTHONDONTWRITEBYTECODE=1 -e MYSQL_PWD \
    -v "$CODE:/code:ro" -v "$SCRIPTS:/scripts:ro" -v "$EXPORT:/export" -v "$XVAL:/xval" \
    "$PY_IMAGE" sleep infinity >/dev/null
  if docker exec "$PY_C" sh -c 'env | grep -qi "^AWS"'; then
    echo "AWS variable in the container environment; aborting" >&2
    exit 1
  fi
  rec docker exec "$PY_C" pip install -q --no-cache-dir --root-user-action=ignore --disable-pip-version-check \
    "mysql-connector-python==$MYSQL_CONNECTOR_PIN"
  docker exec "$PY_C" pip freeze > "$LOGS/pip_freeze.txt"
}

stop_py() {
  docker rm -f "$PY_C" >/dev/null 2>&1 || true
}
