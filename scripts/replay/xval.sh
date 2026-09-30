#!/bin/bash
# Hybrid cross-validation: patched link@405a10c for ~100 sampled configurations on dev medications only.
# Run after replay_405a10c.sh. Requires HAB_MYSQL_PASSWORD in the environment and the repo's `uv`.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
need_password
prepare_dirs
trap stop_py EXIT
REPO=$(cd "$SCRIPTS/../.." && pwd)

# patched sources, configs.json and the dev medication list (dev only; the sealed test partition is never read)
note "uv run python -m habench.historical.xval prepare"
(cd "$REPO" && uv run python -m habench.historical.xval prepare)

mysql_root() { docker exec -i -e MYSQL_PWD "$MYSQL_C" mysql -uroot "$@"; }

note "create schema healdb_xval with ICD tables and dev-only entity/trait rows"
mysql_root <<'SQL'
DROP DATABASE IF EXISTS healdb_xval;
CREATE DATABASE healdb_xval;
CREATE TABLE healdb_xval.hd_icd_group LIKE healdb.hd_icd_group;
CREATE TABLE healdb_xval.hd_icd_category LIKE healdb.hd_icd_category;
CREATE TABLE healdb_xval.hd_icd_subcategory LIKE healdb.hd_icd_subcategory;
CREATE TABLE healdb_xval.hd_int_med_disease_entity LIKE healdb.hd_int_med_disease_entity;
CREATE TABLE healdb_xval.hd_int_med_disease_trait LIKE healdb.hd_int_med_disease_trait;
CREATE TABLE healdb_xval.hd_medication_disease LIKE healdb.hd_medication_disease;
CREATE TABLE healdb_xval.dev_meds (id_medication INT PRIMARY KEY);
INSERT INTO healdb_xval.hd_icd_group SELECT * FROM healdb.hd_icd_group;
INSERT INTO healdb_xval.hd_icd_category SELECT * FROM healdb.hd_icd_category;
INSERT INTO healdb_xval.hd_icd_subcategory SELECT * FROM healdb.hd_icd_subcategory;
SQL
note "mysql < $XVAL/dev_meds.sql"
mysql_root < "$XVAL/dev_meds.sql"
mysql_root <<'SQL'
INSERT INTO healdb_xval.hd_int_med_disease_entity
  SELECT e.* FROM healdb.hd_int_med_disease_entity e JOIN healdb_xval.dev_meds d ON d.id_medication = e.id_medication
  ORDER BY e.id_medication, e.cd_icd_full;
INSERT INTO healdb_xval.hd_int_med_disease_trait
  SELECT t.* FROM healdb.hd_int_med_disease_trait t JOIN healdb_xval.dev_meds d ON d.id_medication = t.id_medication
  ORDER BY t.id_medication, t.cd_icd_full, t.nm_trait;
SELECT 'xval_entity', COUNT(*) FROM healdb_xval.hd_int_med_disease_entity;
SELECT 'xval_trait', COUNT(*) FROM healdb_xval.hd_int_med_disease_trait;
SQL

start_py
s=$(date +%s); rc=0
rec docker exec -u "$(id -u):$(id -g)" -e MYSQL_PWD "$PY_C" python /scripts/driver.py xval \
  > "$LOGS/xval.log" 2>&1 || rc=$?
echo "xval driver rc=$rc in $(( $(date +%s) - s ))s"
tail -n 5 "$LOGS/xval.log"
exit $rc
