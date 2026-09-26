import json
import sys
from pathlib import Path
sys.path.insert(0, ".")
from rule_filter import rule_filter

MUTATIONS_PATH = Path("bird_eval/results/bird_fresh_mutations_dataset.json")

with open(MUTATIONS_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

mutations = data["mutations"]

results = {}
for m in mutations:
    cat = m["mutation_category"]
    exp = m["expected_decision"]
    sql = m["mutated_sql"]
    rule_dec = rule_filter(sql)
    correct = (rule_dec == exp) or (exp == "CONFIRM" and rule_dec in ("CONFIRM", "BLOCK"))
    if cat not in results:
        results[cat] = {"total": 0, "rule_correct": 0, "decisions": {}}
    results[cat]["total"] += 1
    if correct:
        results[cat]["rule_correct"] += 1
    results[cat]["decisions"][rule_dec] = results[cat]["decisions"].get(rule_dec, 0) + 1

print("=== DUMB BLOCKLIST (Rule Filter) on 342 Fresh BIRD Mutations ===")
total_c = sum(d["rule_correct"] for d in results.values())
total_t = sum(d["total"] for d in results.values())
for cat in sorted(results.keys()):
    d = results[cat]
    c = d["rule_correct"]
    t = d["total"]
    print(f"{cat:<25}: {c:>3}/{t:<3} ({c/t*100:>5.1f}%) | {d['decisions']}")
print(f"Total Rule-Filter Accuracy: {total_c}/{total_t} ({total_c/total_t*100:.2f}%)\n")
