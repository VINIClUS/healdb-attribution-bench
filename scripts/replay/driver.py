"""Runs inside the replay python container (no habench import).

  driver.py replay  import process_disease_data_json and link_medications_with_diseases of 405a10c by path, run them
                    unchanged on schema `healdb`, then export entity/trait/md as TSV plus export_meta.json
  driver.py xval    run every patched link of /xval/configs.json on schema `healdb_xval`, export md per config

The connection comes from the environment: MYSQL_PWD (password), optional MYSQL_HOST (default
healdb-replay-mysql). The password is never printed.
TSV format: see habench.historical.replay (NULL as \\N, backslash/tab/newline/CR escaped, floats via repr).
"""

import importlib.util
import json
import os
import sys
import time

import mysql.connector

CODE = "/code/405a10c"
EXPORT = "/export"
XVAL = "/xval"
TABLES = {
    "entity": ("hd_int_med_disease_entity", ("id_medication", "cd_icd_full")),
    "trait": ("hd_int_med_disease_trait", ("id_medication", "cd_icd_full", "nm_trait")),
    "md": ("hd_medication_disease", ("id_med_disease",)),
}


def log(msg):
    print(f'[replay {time.strftime("%F %T")}] {msg}', flush=True)


def connect():
    cnx = mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "healdb-replay-mysql"), user="root", password=os.environ["MYSQL_PWD"],
        database="healdb", charset="utf8mb4", autocommit=False,
    )
    return cnx, cnx.cursor()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def format_cell(v):
    # same semantics as habench.historical.replay.format_cell
    if v is None:
        return "\\N"
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (bytes, bytearray)):
        v = bytes(v).decode("utf-8")
    return v.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def export_table(cursor, schema, table, key, path):
    """ORDER BY primary key; returns the number of rows written."""
    cursor.execute(f"SELECT * FROM {schema}.{table} ORDER BY {', '.join(key)}")
    columns = [d[0] for d in cursor.description]
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(columns) + "\n")
        while True:
            rows = cursor.fetchmany(10000)
            if not rows:
                break
            for row in rows:
                fh.write("\t".join(format_cell(c) for c in row) + "\n")
                n += 1
    return n


def counts(cursor):
    out = []
    for table, _ in TABLES.values():
        cursor.execute(f"SELECT COUNT(*) FROM healdb.{table}")
        out.append(f"{table}={cursor.fetchone()[0]}")
    return " ".join(out)


def stage(name, fn, cnx, cursor):
    t = time.time()
    log(f"start {name}")
    fn(cnx, cursor)
    log(f"end {name}: {time.time() - t:.1f}s | {counts(cursor)}")


def replay():
    t0 = time.time()
    cnx, cursor = connect()
    log(f"versions: python {sys.version.split()[0]}, mysql-connector-python {mysql.connector.__version__}, "
        f"server {cnx.get_server_info()}")
    log(f"before: {counts(cursor)}")
    process = load("process_disease_data_json", f"{CODE}/process_disease_data_json.py")
    link = load("link_medications_with_diseases", f"{CODE}/link_medications_with_diseases.py")
    stage("process_disease_data_json", process.process_disease_data_json, cnx, cursor)
    log("OPERATOR ACTION: TRUNCATE hd_medication_disease (not in the historical code; V1 md ids start at 1)")
    cursor.execute("TRUNCATE healdb.hd_medication_disease")
    cnx.commit()
    stage("link_medications_with_diseases", link.link_medications_with_diseases, cnx, cursor)
    os.makedirs(EXPORT, exist_ok=True)
    meta = {"row_counts": {}, "mysql_version": cnx.get_server_info(), "started": time.strftime("%F %T", time.localtime(t0))}
    for label, (table, key) in TABLES.items():
        meta["row_counts"][label] = export_table(cursor, "healdb", table, key, f"{EXPORT}/{label}.tsv")
        log(f"exported {label}: {meta['row_counts'][label]} rows")
    meta["finished"] = time.strftime("%F %T")
    with open(f"{EXPORT}/export_meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, sort_keys=True)
        fh.write("\n")
    cursor.close()
    cnx.close()
    log(f"total {time.time() - t0:.1f}s")


def xval():
    t0 = time.time()
    with open(f"{XVAL}/configs.json", encoding="utf-8") as fh:
        entries = json.load(fh)
    cnx, cursor = connect()
    log(f"versions: python {sys.version.split()[0]}, mysql-connector-python {mysql.connector.__version__}, "
        f"server {cnx.get_server_info()}")
    for i, e in enumerate(entries, 1):
        t = time.time()
        cursor.execute("TRUNCATE healdb_xval.hd_medication_disease")
        cnx.commit()
        mod = load(f"link_{e['cfg_id']}", f"{XVAL}/{e['cfg_id']}.py")
        mod.link_medications_with_diseases(cnx, cursor)
        n = export_table(cursor, "healdb_xval", "hd_medication_disease", ("id_med_disease",), f"{XVAL}/{e['cfg_id']}.tsv")
        log(f"xval {i}/{len(entries)} {e['cfg_id']}: {time.time() - t:.1f}s | rows={n}")
    cursor.close()
    cnx.close()
    log(f"total {time.time() - t0:.1f}s")


if __name__ == "__main__":
    {"replay": replay, "xval": xval}[sys.argv[1]]()
