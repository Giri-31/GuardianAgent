"""
run_ablation_study.py

Ablation study decomposing GuardianAgent into:
1. "Dumb" Blocklist Component (Simple keyword regex / rule filter)
2. "Smart" Consequence Scoring Component (Weighted multi-attribute scoring without overrides)
3. Full System (Consequence scoring + enterprise policy overrides)

Evaluated across the 342 Fresh BIRD Mutations.
Outputs:
  benchmark/ablation_study_results.json
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["GUARDIAN_DISABLE_LLM"] = "1"

import risk_engine
from rule_filter import rule_filter
from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

MUTATIONS_PATH = ROOT / "bird_eval" / "results" / "bird_fresh_mutations_dataset.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
OUTPUT_PATH = ROOT / "benchmark" / "ablation_study_results.json"


def run_ablation():
    print("=" * 80)
    print("GUARDIANAGENT COMPONENT ABLATION STUDY: SMART SCORING VS. DUMB BLOCKLIST")
    print("=" * 80)

    with open(MUTATIONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    mutations = data["mutations"]
    total = len(mutations)
    print(f"Evaluated on: {total} Fresh BIRD Mutations across 10 Unseen Databases\n")

    # 1. Evaluate Dumb Blocklist (Rule Filter)
    rule_results = defaultdict(lambda: {"total": 0, "correct": 0})
    for m in mutations:
        cat = m["mutation_category"]
        exp = m["expected_decision"]
        sql = m["mutated_sql"]
        dec = rule_filter(sql)
        corr = (dec == exp) or (exp == "CONFIRM" and dec in ("CONFIRM", "BLOCK"))
        rule_results[cat]["total"] += 1
        if corr:
            rule_results[cat]["correct"] += 1

    # 2. Evaluate Pure Smart Scoring (No Hardcoded Overrides)
    orig_overrides = risk_engine._apply_safety_overrides
    risk_engine._apply_safety_overrides = lambda op, mismatches, scope, imp, score: score

    adapter = GuardianBIRDAdapter(disable_llm_intent=True)
    scoring_results = defaultdict(lambda: {"total": 0, "correct": 0, "caught": 0})

    for m in mutations:
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

        def is_correct_decision(e, a):
            if e == "BLOCK":
                return a == "BLOCK"
            elif e == "CONFIRM":
                return a in ("BLOCK", "CONFIRM")
            elif e == "ALLOW":
                return a == "ALLOW"
            return False

        act = res["decision"]
        corr = is_correct_decision(exp, act)
        caught = act in ("CONFIRM", "BLOCK")

        scoring_results[cat]["total"] += 1
        if corr:
            scoring_results[cat]["correct"] += 1
        if caught:
            scoring_results[cat]["caught"] += 1

    # Restore overrides
    risk_engine._apply_safety_overrides = orig_overrides

    # 3. Full System Results (Load from fresh mutation eval results)
    with open(ROOT / "bird_eval" / "results" / "bird_fresh_mutation_eval_results.json", "r", encoding="utf-8") as f:
        full_eval = json.load(f)

    full_results = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in full_eval:
        cat = r["category"]
        full_results[cat]["total"] += 1
        if r["decision_correct"]:
            full_results[cat]["correct"] += 1

    # Print Table
    print(f"{'Category':<24} {'Total':<6} {'Dumb Blocklist':<18} {'Pure Scoring':<18} {'Full System':<15}")
    print("-" * 85)

    all_cats = sorted(rule_results.keys())
    total_rule = sum(rule_results[c]["correct"] for c in all_cats)
    total_scoring = sum(scoring_results[c]["correct"] for c in all_cats)
    total_full = sum(full_results[c]["correct"] for c in all_cats)

    for cat in all_cats:
        tot = rule_results[cat]["total"]
        r_c = rule_results[cat]["correct"]
        s_c = scoring_results[cat]["correct"]
        f_c = full_results[cat]["correct"]
        print(
            f"{cat:<24} {tot:<6} "
            f"{r_c:>3}/{tot:<3} ({r_c/tot*100:>5.1f}%)   "
            f"{s_c:>3}/{tot:<3} ({s_c/tot*100:>5.1f}%)   "
            f"{f_c:>3}/{tot:<3} ({f_c/tot*100:>5.1f}%)"
        )

    print("-" * 85)
    print(
        f"{'OVERALL ACCURACY':<24} {total:<6} "
        f"{total_rule:>3}/{total:<3} ({total_rule/total*100:>5.1f}%)   "
        f"{total_scoring:>3}/{total:<3} ({total_scoring/total*100:>5.1f}%)   "
        f"{total_full:>3}/{total:<3} ({total_full/total*100:>5.1f}%)"
    )

    # Subtle / Semantic subset
    semantic_cats = ["FIELD_INJECT", "SCOPE_ESCALATION", "TARGET_MISMATCH"]
    sem_tot = sum(rule_results[c]["total"] for c in semantic_cats)
    sem_rule = sum(rule_results[c]["correct"] for c in semantic_cats)
    sem_scoring = sum(scoring_results[c]["correct"] for c in semantic_cats)
    sem_full = sum(full_results[c]["correct"] for c in semantic_cats)

    print(
        f"{'Subtle / Semantic Only':<24} {sem_tot:<6} "
        f"{sem_rule:>3}/{sem_tot:<3} ({sem_rule/sem_tot*100:>5.1f}%)   "
        f"{sem_scoring:>3}/{sem_tot:<3} ({sem_scoring/sem_tot*100:>5.1f}%)   "
        f"{sem_full:>3}/{sem_tot:<3} ({sem_full/sem_tot*100:>5.1f}%)"
    )

    output_data = {
        "benchmark": "BIRD 342 Fresh Mutations",
        "total_cases": total,
        "dumb_blocklist_accuracy_pct": round(total_rule / total * 100, 2),
        "pure_scoring_accuracy_pct": round(total_scoring / total * 100, 2),
        "full_system_accuracy_pct": round(total_full / total * 100, 2),
        "semantic_attacks": {
            "total": sem_tot,
            "dumb_blocklist_accuracy_pct": round(sem_rule / sem_tot * 100, 2),
            "pure_scoring_accuracy_pct": round(sem_scoring / sem_tot * 100, 2),
            "full_system_accuracy_pct": round(sem_full / sem_tot * 100, 2),
        },
        "per_category": {
            cat: {
                "total": rule_results[cat]["total"],
                "dumb_blocklist": rule_results[cat]["correct"],
                "pure_scoring": scoring_results[cat]["correct"],
                "full_system": full_results[cat]["correct"],
            }
            for cat in all_cats
        }
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
    print(f"\nAblation results saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    run_ablation()
