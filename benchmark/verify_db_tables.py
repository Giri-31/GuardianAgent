import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbbench_loader import load_dbbench

def quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'

def create_temp_database(table):
    conn = sqlite3.connect(":memory:")
    table_name = table["table_name"]
    columns = table["table_info"]["columns"]
    rows = table["table_info"]["rows"]
    column_names = [c["name"] for c in columns]

    col_defs = ", ".join(f"{quote_identifier(name)} TEXT" for name in column_names)
    create_sql = f"CREATE TABLE {quote_identifier(table_name)} ({col_defs})"
    conn.execute(create_sql)

    placeholders = ", ".join(["?"] * len(column_names))
    insert_sql = f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quote_identifier(c) for c in column_names)}) VALUES ({placeholders})"
    for row in rows:
        conn.execute(insert_sql, [None if v is None else str(v) for v in row])
    conn.commit()
    return conn

tasks = load_dbbench()
errors = 0
for t in tasks:
    try:
        conn = create_temp_database(t["table"])
        # Check table count
        cur = conn.cursor()
        tname = t["table"]["table_name"]
        cur.execute(f"SELECT COUNT(*) FROM {quote_identifier(tname)}")
        cnt = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        errors += 1
        print(f"Task {t['case_id']} DB creation error: {e}")

print(f"Table creation check complete. Errors: {errors}/60")
