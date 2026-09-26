import json
import sys
import os
from pathlib import Path

os.environ["GUARDIAN_DISABLE_LLM"] = "1"
sys.path.insert(0, ".")

import risk_engine

# Monkey-patch _apply_safety_overrides to return just the weighted score
def no_overrides(operation, mismatches, scope, impact_level, risk_score):
    return risk_score

risk_engine._apply_safety_overrides = no_overrides

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DEV_DATABASES_DIR = Path("bird_eval/databases/data_minidev/MINIDEV/dev_databases")
with open("bird_eval/results/bird_fresh_mutations_dataset.json", "r", encoding="utf-8") as f:
    data = json.load(f)

adapter = GuardianBIRDAdapter(disable_llm_intent=True)

correct = 0
total = len(data["mutations"])
cat_stats = {}

for m in data["mutations"]:
    cat = m["mutation_category"]
    exp = m["expected_decision"]
    db_id = m["db_id"]
    db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
    if not db_path.exists():
        matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
        if matches:
            db_path = matches[0]
    conn = adapter.open_database_connection(db_path, read_only=True)
    res = adapter.evaluate_query(m["original_question"], m["mutated_sql"], connection=conn)
    conn.close()

    act = res["decision"]
    is_corr = (act == exp) or (exp == "CONFIRM" and act in ("CONFIRM", "BLOCK"))
    if cat not in cat_stats:
        cat_stats[cat] = {"correct": 0, "total": 0, "decisions": {}}
    cat_stats[cat]["total"] += 1
    cat_stats[cat]["decisions"][act] = cat_stats[cat]["decisions"].get(act, 0) + 1
    if is_corr:
        correct += 1
        cat_stats[cat]["correct"] += 1

print("=== PURE WEIGHTED SCORING (NO HARD OVERRIDES) on 342 Fresh BIRD Mutations ===")
print(f"Total Correct: {correct}/{total} ({correct/total*100:.2f}%)\n")
for cat, s in sorted(cat_stats.items()):
    c = s["correct"]
    t = s["total"]
    print(f"{cat:<25}: {c:>3}/{t:<3} ({c/t*100:>5.1f}%) | {s['decisions']}")
