#!/bin/bash
# Start MySQL 8.0.33 for the replay of 405a10c and load the V1 dump into schema `healdb`:
# api_response and the ICD tables with data; entity, trait and medication_disease as DDL only.
# Requires HAB_MYSQL_PASSWORD in the environment. Logs: $LOGS/up.log, images.txt, commands.log.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
need_password
prepare_dirs
: > "$LOGS/up.log"
: > "$LOGS/commands.log"

: > "$LOGS/images.txt.new"
for img in "$MYSQL_IMAGE" "$PY_IMAGE"; do
  docker image inspect --format '{{index .RepoTags 0}} {{.Id}} {{json .RepoDigests}}' "$img" >> "$LOGS/images.txt.new"
done
mv "$LOGS/images.txt.new" "$LOGS/images.txt"

rec docker network create "$NET" >/dev/null 2>&1 || note "network $NET already exists"
rec docker run -d --name "$MYSQL_C" --network "$NET" -e MYSQL_ROOT_PASSWORD \
  -v "$VOL:/var/lib/mysql" -v "$DUMPS:/x:ro" "$MYSQL_IMAGE" \
  --skip-log-bin --innodb-buffer-pool-size=1G --innodb-flush-log-at-trx-commit=0 \
  --innodb-doublewrite=0 --max-allowed-packet=1G --innodb-log-file-size=512M

# -h 127.0.0.1: the temporary initialisation server does not listen on TCP
until docker exec -e MYSQL_PWD "$MYSQL_C" mysqladmin -uroot -h127.0.0.1 ping 2>/dev/null | grep -q alive; do sleep 2; done
rec docker exec -e MYSQL_PWD "$MYSQL_C" mysql -uroot -e "CREATE DATABASE IF NOT EXISTS healdb"

report() { # schema table status seconds
  echo "load $1 $2 $3 $4s" | tee -a "$LOGS/up.log"
}

load_data() { # table: full dump file
  local t=$1 s st=OK
  s=$(date +%s)
  note "mysql healdb < $DUMPS/$V1_DIR/healdb_$t.sql"
  docker exec -i -e MYSQL_PWD "$MYSQL_C" mysql -uroot --default-character-set=utf8mb4 healdb \
    < "$DUMPS/$V1_DIR/healdb_$t.sql" 2>>"$LOGS/up.err" || st=ERR
  report healdb "$t" "$st" $(( $(date +%s) - s ))
}

load_ddl() { # table: CREATE TABLE only
  local t=$1 s st=OK
  s=$(date +%s)
  note "python ddl_only.py healdb_$t.sql | mysql healdb"
  docker run --rm -i --user "$(id -u):$(id -g)" -v "$DUMPS:/x:ro" -v "$SCRIPTS:/scripts:ro" "$PY_IMAGE" \
    python /scripts/ddl_only.py "/x/$V1_DIR/healdb_$t.sql" \
    | docker exec -i -e MYSQL_PWD "$MYSQL_C" mysql -uroot --default-character-set=utf8mb4 healdb \
    2>>"$LOGS/up.err" || st=ERR
  report healdb "$t" "$st" $(( $(date +%s) - s ))
}

for t in hd_icd_group hd_icd_category hd_icd_subcategory hd_int_med_disease_api_response; do
  load_data "$t"
done
for t in hd_int_med_disease_entity hd_int_med_disease_trait hd_medication_disease; do
  load_ddl "$t"
done

docker exec -i -e MYSQL_PWD "$MYSQL_C" mysql -uroot -N 2>&1 <<'SQL' | grep -v Warning | tee -a "$LOGS/up.log" || true
SELECT 'version', @@version;
SELECT 'api_response', COUNT(*) FROM healdb.hd_int_med_disease_api_response;
SELECT 'icd_subcategory', COUNT(*) FROM healdb.hd_icd_subcategory;
SELECT 'entity', COUNT(*) FROM healdb.hd_int_med_disease_entity;
SQL
echo LOAD_DONE | tee -a "$LOGS/up.log"
