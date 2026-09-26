import json
import os
import sys
sys.path.insert(0, ".")
from pathlib import Path
from scratch.test_calibration import DEV_DATABASES_DIR, clean_cases, adapter

for item in clean_cases:
    db_id = item["db_id"]
    db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
    if not db_path.exists():
        matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
        if matches: db_path = matches[0]
    conn = adapter.open_database_connection(db_path, read_only=True)
    res = adapter.evaluate_query(item["q"], item["sql"], connection=conn)
    conn.close()
    if res["decision"] == "BLOCK":
        print(f"QID {item['qid']}: {item['q']}")
        print(f"  SQL: {item['sql']}")
        print(f"  Intent: {res['intent']}")
        print(f"  Mismatches: {res['mismatches']}")
        print(f"  Risk: {res['risk_score']}")
