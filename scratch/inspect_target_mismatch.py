import json
import sys
sys.path.insert(0, ".")
from pathlib import Path
from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DEV_DATABASES_DIR = Path("bird_eval/databases/data_minidev/MINIDEV/dev_databases")
with open("bird_eval/results/bird_fresh_mutations_dataset.json", encoding="utf-8") as f:
    data = json.load(f)

adapter = GuardianBIRDAdapter(disable_llm_intent=True)
count = 0
for m in data["mutations"]:
    if m["mutation_category"] == "TARGET_MISMATCH":
        db_id = m["db_id"]
        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        conn = adapter.open_database_connection(db_path, read_only=True)
        res = adapter.evaluate_query(m["original_question"], m["mutated_sql"], connection=conn)
        conn.close()
        if "TARGET_MISMATCH" not in res.get("mismatches", []):
            count += 1
            print(f"Case {count}: QID {m['source_question_id']}")
            print(f"  Q: {m['original_question']}")
            print(f"  Mutated SQL: {m['mutated_sql']}")
            print(f"  Intent: {res['intent']}")
            print(f"  SQL Info: {res['sql_info']}")
            print(f"  Mismatches: {res.get('mismatches')}")
            print(f"  Decision: {res['decision']}, Risk: {res['risk_score']}")
            if count >= 5:
                break
