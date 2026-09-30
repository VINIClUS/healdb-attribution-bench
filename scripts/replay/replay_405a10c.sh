#!/bin/bash
# Run process_disease_data_json and link_medications_with_diseases of 405a10c, unchanged, against the loaded
# `healdb` schema and export entity/trait/md. Run after up.sh. Requires HAB_MYSQL_PASSWORD in the environment.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
need_password
prepare_dirs
trap stop_py EXIT

# materialise the two historical files and check their git blobs
mkdir -p "$CODE/405a10c"
: > "$LOGS/blobs.txt"
declare -A EXPECT=([process_disease_data_json.py]=02d294c [link_medications_with_diseases.py]=c9c4aeb)
for f in process_disease_data_json.py link_medications_with_diseases.py; do
  blob=$(git -C "$HEALDB_REPO" rev-parse "405a10c:src/nlp_extraction/$f")
  case "$blob" in
    "${EXPECT[$f]}"*) ;;
    *) echo "unexpected blob $blob for $f (expected ${EXPECT[$f]}...)" >&2; exit 1 ;;
  esac
  git -C "$HEALDB_REPO" cat-file blob "$blob" > "$CODE/405a10c/$f"
  note "git -C $HEALDB_REPO cat-file blob $blob > $CODE/405a10c/$f"
  echo "blob_ok $blob $f" >> "$LOGS/blobs.txt"
  [ "$(git -C "$HEALDB_REPO" hash-object --no-filters "$CODE/405a10c/$f")" = "$blob" ] \
    || { echo "materialised file differs from blob $blob" >&2; exit 1; }
done
echo "commit $(git -C "$HEALDB_REPO" rev-parse 405a10c) src/nlp_extraction" >> "$LOGS/blobs.txt"

start_py

s=$(date +%s); rc=0
rec docker exec -u "$(id -u):$(id -g)" -e MYSQL_PWD "$PY_C" python /scripts/driver.py replay \
  > "$LOGS/replay_405a10c.log" 2>&1 || rc=$?
echo "driver rc=$rc in $(( $(date +%s) - s ))s; 'Error' lines in the log: $(grep -c '^Error' "$LOGS/replay_405a10c.log" || true)"
tail -n 8 "$LOGS/replay_405a10c.log"
exit $rc
