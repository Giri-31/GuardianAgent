"""
evaluate_benign_queries.py

Evaluates GuardianAgent on the 50 original, benign, gold-standard queries
from the exact same 10 fresh held-out BIRD databases used in the mutation benchmark.

Measures:
- True Allow Rate (Harmless queries correctly allowed without interruption)
- False Alarm / Interruption Rate (Harmless queries triggering CONFIRM or BLOCK)
- False Block Rate (Harmless queries wrongly rejected outright)
- Latency and root-cause breakdown of false alarms.
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure deterministic mode for fast, reproducible sub-millisecond evaluation
os.environ["GUARDIAN_DISABLE_LLM"] = "1"

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DATASET_PATH = ROOT / "bird_eval" / "results" / "bird_fresh_mutations_dataset.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
OUTPUT_PATH = ROOT / "bird_eval" / "results" / "bird_fresh_benign_eval_results.json"


def run_benign_evaluation():
    print("=" * 80)
    print("BIRD FRESH HELD-OUT BENIGN / SAFE QUERY EVALUATION (FALSE ALARM TEST)")
    print("=" * 80)

    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Dataset not found at {DATASET_PATH}")

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract unique source questions (the clean, gold queries)
    seen_qids = set()
    clean_cases = []
    for m in data["mutations"]:
        qid = m["source_question_id"]
        if qid not in seen_qids:
            seen_qids.add(qid)
            clean_cases.append({
                "source_question_id": qid,
                "db_id": m["db_id"],
                "original_question": m["original_question"],
                "gold_sql": m["gold_sql"],
                "evidence": m.get("evidence", ""),
            })

    print(f"Total benign gold queries to evaluate: {len(clean_cases)} across 10 databases\n")

    adapter = GuardianBIRDAdapter(disable_llm_intent=True)

    results = []
    decisions = Counter()
    db_stats = defaultdict(lambda: Counter())
    mismatch_causes = Counter()
    latencies = []

    print(f"{'#':<4} {'DB':<22} {'Expected':<10} {'Actual':<10} {'Risk':<6} {'Mismatches':<25}")
    print("-" * 80)

    for idx, item in enumerate(clean_cases, start=1):
        db_id = item["db_id"]
        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            if matches:
                db_path = matches[0]

        conn = None
        try:
            conn = adapter.open_database_connection(db_path, read_only=True)
            res = adapter.evaluate_query(
                user_request=item["original_question"],
                sql=item["gold_sql"],
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

        decision = res["decision"]
        risk_score = res["risk_score"]
        mismatches = res.get("mismatches", [])
        latency = res["latency_ms"]

        decisions[decision] += 1
        db_stats[db_id][decision] += 1
        latencies.append(latency)
        for m in mismatches:
            mismatch_causes[m] += 1

        print(
            f"{idx:<4} {db_id[:21]:<22} {'ALLOW':<10} {decision:<10} "
            f"{risk_score:<6.2f} {str(mismatches)[:25]:<25}"
        )

        results.append({
            "source_question_id": item["source_question_id"],
            "db_id": db_id,
            "original_question": item["original_question"],
            "gold_sql": item["gold_sql"],
            "expected_decision": "ALLOW",
            "guardian_decision": decision,
            "risk_score": risk_score,
            "mismatches": mismatches,
            "latency_ms": latency,
        })

    total = len(clean_cases)
    allow_count = decisions.get("ALLOW", 0)
    confirm_count = decisions.get("CONFIRM", 0)
    block_count = decisions.get("BLOCK", 0)

    allow_rate = (allow_count / total) * 100
    confirm_rate = (confirm_count / total) * 100
    false_block_rate = (block_count / total) * 100
    interruption_rate = ((confirm_count + block_count) / total) * 100

    print("\n" + "=" * 80)
    print("BENIGN QUERY EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Benign Queries Evaluated : {total}")
    print(f"Direct Autonomous ALLOW       : {allow_count} ({allow_rate:.1f}%)")
    print(f"Human Confirmation (CONFIRM)   : {confirm_count} ({confirm_rate:.1f}%)")
    print(f"False BLOCK (False Alarm Wipes): {block_count} ({false_block_rate:.1f}%)")
    print(f"Total Interruption Rate       : {confirm_count + block_count} / {total} ({interruption_rate:.1f}%)")
    print(f"Mean Verification Latency      : {sum(latencies)/len(latencies):.3f} ms")
    print("\nTop Root Causes of False Interruptions:")
    for cause, cnt in mismatch_causes.most_common():
        print(f"  {cause:<24}: {cnt} occurrences")

    summary = {
        "total_benign_queries": total,
        "allow_count": allow_count,
        "allow_rate_pct": round(allow_rate, 2),
        "confirm_count": confirm_count,
        "confirm_rate_pct": round(confirm_rate, 2),
        "false_block_count": block_count,
        "false_block_rate_pct": round(false_block_rate, 2),
        "total_interruption_rate_pct": round(interruption_rate, 2),
        "mean_latency_ms": round(sum(latencies)/len(latencies), 3),
        "decision_counts": dict(decisions),
        "db_breakdown": {db: dict(counts) for db, counts in db_stats.items()},
        "mismatch_causes": dict(mismatch_causes),
        "details": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nDetailed benign query results saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    run_benign_evaluation()
