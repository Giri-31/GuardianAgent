"""
find_9th_escape.py — No GuardianAgent code changes. Read-only audit.
"""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('bird_eval/results/bird_fresh_mutation_eval_results.json', encoding='utf-8') as f:
    results = json.load(f)

print("=== ALL 9 AUTONOMOUS ESCAPES BY CATEGORY ===\n")
escapes = [r for r in results if r['guardian_decision'] == 'ALLOW']
for i, r in enumerate(escapes, 1):
    db = r['db_id']
    cat = r['category']
    exp = r['expected_decision']
    risk = r['risk_score']
    mm = r['mismatches']
    q = r['original_question']
    sql = r['mutated_sql']
    print(f"Escape #{i} | Cat={cat} | DB={db} | Expected={exp} | Risk={risk}")
    print(f"  Mismatches: {mm}")
    print(f"  Request: {q}")
    print(f"  Mutated SQL: {sql[:200]}")
    print()

print("\n=== CATEGORY BREAKDOWN ===")
from collections import Counter
cat_count = Counter(r['category'] for r in escapes)
for cat, cnt in cat_count.most_common():
    print(f"  {cat}: {cnt}")
