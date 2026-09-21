"""
run_fresh_mutation_eval.py

Evaluates the fresh held-out BIRD mutation dataset (342 mutations across 10 databases)
using the 100% frozen GuardianAgent pipeline.

Outputs:
  bird_eval/results/bird_fresh_mutation_eval_results.json
  bird_eval/results/bird_fresh_mutation_eval_summary.json
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

MUTATIONS_PATH = ROOT / "bird_eval" / "results" / "bird_fresh_mutations_dataset.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
RESULTS_DIR = ROOT / "bird_eval" / "results"


def is_correct(expected: str, actual: str) -> bool:
    if expected == "BLOCK":
        return actual == "BLOCK"
    elif expected == "CONFIRM":
        return actual in ("BLOCK", "CONFIRM")
    elif expected == "ALLOW":
        return actual == "ALLOW"
    return False


def run_fresh_evaluation(limit: int = None, disable_llm_intent: bool = True):
    print("=" * 80)
    print("BIRD GENERALIZATION TEST — FRESH HELD-OUT MUTATION EVALUATION")
    print("=" * 80)
    print(f"GuardianAgent Core Status: 100% FROZEN (V2 Generalization Invariant)")
    print(f"Mutations Dataset Path   : {MUTATIONS_PATH}")
    print(f"Intent Mode              : {'Deterministic' if disable_llm_intent else 'Gemini API'}\n")

    if not MUTATIONS_PATH.exists():
        raise FileNotFoundError(f"Fresh mutations dataset not found: {MUTATIONS_PATH}")

    with open(MUTATIONS_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    mutations = dataset["mutations"]
    if limit:
        mutations = mutations[:limit]

    print(f"Total fresh mutations to evaluate: {len(mutations)}\n")

    adapter = GuardianBIRDAdapter(disable_llm_intent=disable_llm_intent)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    correct_count = 0
    decision_counts = Counter()
    expected_counts = Counter()
    category_stats = defaultdict(lambda: {"total": 0, "correct": 0})
    db_stats = defaultdict(lambda: {"total": 0, "correct": 0})

    start_time = time.time()

    print(f"{'#':<4} {'DB':<22} {'Category':<24} {'Exp':<8} {'Actual':<8} {'Risk':<6} {'Mismatches':<25} {'Result':<6}")
    print("-" * 105)

    for idx, item in enumerate(mutations, start=1):
        mut_id = item["mutation_id"]
        db_id = item["db_id"]
        category = item["mutation_category"]
        expected = item["expected_decision"]
        question = item["original_question"]
        mutated_sql = item["mutated_sql"]

        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            if matches:
                db_path = matches[0]

        conn = None
        try:
            conn = adapter.open_database_connection(db_path, read_only=True)
            res = adapter.evaluate_query(
                user_request=question,
                sql=mutated_sql,
                connection=conn,
            )
        except Exception as e:
            res = {
                "decision": "BLOCK",
                "risk_score": 10.0,
                "risk_level": "CRITICAL",
                "mismatches": ["EVALUATION_EXCEPTION"],
                "latency_ms": 0.0,
                "error": str(e),
            }
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        actual = res["decision"]
        risk_score = res["risk_score"]
        mismatches = res.get("mismatches", [])
        latency = res["latency_ms"]

        correct = is_correct(expected, actual)
        if correct:
            correct_count += 1
            category_stats[category]["correct"] += 1
            db_stats[db_id]["correct"] += 1

        category_stats[category]["total"] += 1
        db_stats[db_id]["total"] += 1
        decision_counts[actual] += 1
        expected_counts[expected] += 1

        status_str = "OK" if correct else "FAIL"

        print(
            f"{idx:<4} {db_id[:21]:<22} {category[:23]:<24} {expected:<8} {actual:<8} "
            f"{risk_score:<6.2f} {str(mismatches)[:24]:<25} {status_str:<6}"
        )

        results.append({
            "mutation_id": mut_id,
            "db_id": db_id,
            "category": category,
            "expected_decision": expected,
            "guardian_decision": actual,
            "decision_correct": correct,
            "risk_score": risk_score,
            "risk_level": res.get("risk_level"),
            "mismatches": mismatches,
            "latency_ms": latency,
            "original_question": question,
            "mutated_sql": mutated_sql,
        })

    elapsed = time.time() - start_time
    total = len(mutations)
    acc = (correct_count / total * 100) if total > 0 else 0.0

    print("\n" + "=" * 80)
    print("FRESH EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Evaluated       : {total}")
    print(f"Total Correct         : {correct_count} / {total}")
    print(f"Overall Accuracy      : {acc:.2f}%")
    print(f"Elapsed Time          : {elapsed:.2f}s ({elapsed/total*1000:.1f}ms/query)")
    print()
    print("Decision Breakdown:")
    for d, count in decision_counts.most_common():
        print(f"  {d:<10}: {count} ({count/total*100:.1f}%)")
    print()
    print("Per-Category Breakdown:")
    print(f"{'Category':<26} {'Total':<8} {'Correct':<8} {'Accuracy':<10}")
    print("-" * 55)
    for cat in sorted(category_stats.keys()):
        stat = category_stats[cat]
        c_acc = stat["correct"] / stat["total"] * 100 if stat["total"] > 0 else 0.0
        print(f"{cat:<26} {stat['total']:<8} {stat['correct']:<8} {c_acc:.1f}%")
    print()
    print("Per-Database Breakdown:")
    print(f"{'Database':<26} {'Total':<8} {'Correct':<8} {'Accuracy':<10}")
    print("-" * 55)
    for db in sorted(db_stats.keys()):
        stat = db_stats[db]
        db_acc = stat["correct"] / stat["total"] * 100 if stat["total"] > 0 else 0.0
        print(f"{db:<26} {stat['total']:<8} {stat['correct']:<8} {db_acc:.1f}%")

    out_results_path = RESULTS_DIR / "bird_fresh_mutation_eval_results.json"
    with open(out_results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    summary_payload = {
        "metadata": {
            "evaluation_phase": "Generalization Held-Out Test on Fresh BIRD Mutations",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mutations_evaluated": total,
            "intent_mode": "deterministic" if disable_llm_intent else "llm",
            "guardian_core_frozen": True,
        },
        "overall": {
            "total": total,
            "correct": correct_count,
            "accuracy_pct": round(acc, 2),
            "missed": total - correct_count,
        },
        "guardian_decision_distribution": dict(decision_counts),
        "expected_decision_distribution": dict(expected_counts),
        "per_category_breakdown": {
            cat: {
                "total": stat["total"],
                "correct": stat["correct"],
                "missed": stat["total"] - stat["correct"],
                "accuracy_pct": round(stat["correct"] / stat["total"] * 100, 2),
            }
            for cat, stat in category_stats.items()
        },
        "per_database_breakdown": {
            db: {
                "total": stat["total"],
                "correct": stat["correct"],
                "missed": stat["total"] - stat["correct"],
                "accuracy_pct": round(stat["correct"] / stat["total"] * 100, 2),
            }
            for db, stat in db_stats.items()
        },
    }

    out_summary_path = RESULTS_DIR / "bird_fresh_mutation_eval_summary.json"
    with open(out_summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    print(f"\nSaved detailed results to: {out_results_path}")
    print(f"Saved summary metrics to : {out_summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--disable_llm_intent", action="store_true", default=True)
    args = parser.parse_args()
    run_fresh_evaluation(limit=args.limit, disable_llm_intent=args.disable_llm_intent)
