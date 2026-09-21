"""
run_bird_eval.py

Phase 1 Prototype Runner for BIRD SQLite Evaluation with GuardianAgent.
Evaluates the first 50 questions from the official BIRD Mini-Dev dataset.

For each question:
1. Loads question, database ID, evidence, and gold SQL.
2. Connects safely in read-only mode to the real BIRD SQLite database.
3. Executes the gold SQL safely to verify ground-truth execution.
4. Passes the natural language question and SQL through the GuardianAgent safety pipeline.
5. Records decisions, risk scores, detected mismatches, and execution metrics.
6. Saves detailed case logs and an aggregated summary.
"""

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter  # noqa: E402

DATA_PATH = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "mini_dev_sqlite.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
RESULTS_DIR = ROOT / "bird_eval" / "results"


def run_phase1_evaluation(num_questions: int = 50, disable_llm_intent: bool = False):
    print("=" * 80)
    print(f"BIRD EVALUATION — PHASE 1 PROTOTYPE ({num_questions} QUESTIONS)")
    print("=" * 80)
    print(f"Dataset Path : {DATA_PATH}")
    print(f"Databases Dir: {DEV_DATABASES_DIR}")
    print(f"Intent Mode  : {'Deterministic (GUARDIAN_DISABLE_LLM=1)' if disable_llm_intent else 'Gemini API'}")
    print()

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"BIRD dataset file not found: {DATA_PATH}")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        all_tasks = json.load(f)

    tasks = all_tasks[:num_questions]
    print(f"Loaded {len(tasks)} questions for Phase 1 prototype evaluation.\n")

    adapter = GuardianBIRDAdapter(disable_llm_intent=disable_llm_intent)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    decision_counts = Counter()
    mismatch_counts = Counter()
    exec_success_count = 0

    print(f"{'#':<4} {'QID':<6} {'DB_ID':<25} {'Exec':<8} {'Guardian':<10} {'Risk':<6} {'Mismatches':<25}")
    print("-" * 88)

    for idx, item in enumerate(tasks, start=1):
        qid = item.get("question_id")
        db_id = item.get("db_id")
        question = item.get("question")
        evidence = item.get("evidence", "")
        gold_sql = item.get("SQL", "").strip()

        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            # Handle potential case-sensitivity or subfolder structure
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            if matches:
                db_path = matches[0]

        # 1. Safe execution test on SQLite database (read-only)
        exec_status = "NOT_ATTEMPTED"
        exec_error = None
        exec_rows = None
        sample_output = None

        conn = None
        try:
            conn = adapter.open_database_connection(db_path, read_only=True)
            cursor = conn.cursor()
            cursor.execute(gold_sql)
            rows = cursor.fetchall()
            exec_status = "EXECUTED_SUCCESS"
            exec_rows = len(rows)
            sample_output = str(rows[:2]) if rows else "[]"
            exec_success_count += 1
        except Exception as e:
            exec_status = "EXECUTION_ERROR"
            exec_error = str(e)
        finally:
            if conn:
                conn.close()

        # 2. GuardianAgent Safety Analysis
        # Open connection for scope analysis
        conn_for_guardian = None
        try:
            conn_for_guardian = adapter.open_database_connection(db_path, read_only=True)
            guardian_res = adapter.evaluate_query(
                user_request=question,
                sql=gold_sql,
                connection=conn_for_guardian,
            )
        finally:
            if conn_for_guardian:
                conn_for_guardian.close()

        decision = guardian_res["decision"]
        risk_score = guardian_res["risk_score"]
        mismatches = guardian_res["mismatches"]

        decision_counts[decision] += 1
        for m in mismatches:
            mismatch_counts[m] += 1
        if not mismatches:
            mismatch_counts["NONE"] += 1

        mismatch_str = ",".join(mismatches) if mismatches else "NONE"
        print(f"[{idx:<2}] {qid:<6} {db_id[:24]:<25} {exec_status[:7]:<8} {decision:<10} {risk_score:<6.2f} {mismatch_str[:25]:<25}")

        record = {
            "index": idx,
            "question_id": qid,
            "db_id": db_id,
            "original_question": question,
            "evidence": evidence,
            "gold_sql": gold_sql,
            "generated_or_mutated_sql": gold_sql,
            "mutation_category": "SAFE_GOLD_SQL",
            "expected_decision": "ALLOW",
            "guardian_decision": decision,
            "decision_matches_expected": (decision == "ALLOW"),
            "risk_score": risk_score,
            "risk_level": guardian_res["risk_level"],
            "scope": guardian_res["scope"],
            "impact": guardian_res["impact"],
            "mismatches": mismatches,
            "intent": guardian_res["intent"],
            "execution_status": exec_status,
            "execution_rows_count": exec_rows,
            "sample_output": sample_output,
            "execution_error": exec_error,
            "latency_ms": guardian_res["latency_ms"],
        }
        results.append(record)

    # Compile Summary
    latencies = [r["latency_ms"] for r in results]
    summary = {
        "metadata": {
            "evaluation_phase": "Phase 1: Small Prototype (50 BIRD SQLite Questions)",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset": str(DATA_PATH.relative_to(ROOT)),
            "total_questions_evaluated": len(results),
            "intent_mode": "deterministic" if disable_llm_intent else "gemini_api",
            "databases_represented": list(set(r["db_id"] for r in results)),
        },
        "execution_summary": {
            "total_gold_queries": len(results),
            "executed_successfully": exec_success_count,
            "execution_errors": len(results) - exec_success_count,
            "execution_success_rate_pct": round((exec_success_count / len(results)) * 100, 2),
        },
        "guardian_decisions_distribution": {
            "ALLOW": decision_counts.get("ALLOW", 0),
            "CONFIRM": decision_counts.get("CONFIRM", 0),
            "BLOCK": decision_counts.get("BLOCK", 0),
            "allow_rate_pct": round((decision_counts.get("ALLOW", 0) / len(results)) * 100, 2),
            "confirm_rate_pct": round((decision_counts.get("CONFIRM", 0) / len(results)) * 100, 2),
            "block_rate_pct": round((decision_counts.get("BLOCK", 0) / len(results)) * 100, 2),
        },
        "mismatches_distribution": dict(mismatch_counts),
        "latency_stats_ms": {
            "mean": round(sum(latencies) / len(latencies), 2),
            "min": round(min(latencies), 2),
            "max": round(max(latencies), 2),
        },
    }

    # Save to JSON
    output_eval_path = RESULTS_DIR / "bird_mini_dev_50_eval.json"
    output_summary_path = RESULTS_DIR / "bird_mini_dev_50_summary.json"

    with open(output_eval_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    with open(output_summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("PHASE 1 EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Evaluated Questions : {len(results)}")
    print(f"Gold SQL Execution Success: {exec_success_count}/{len(results)} ({summary['execution_summary']['execution_success_rate_pct']}%)")
    print(f"Guardian Decisions        : ALLOW={decision_counts['ALLOW']}, CONFIRM={decision_counts['CONFIRM']}, BLOCK={decision_counts['BLOCK']}")
    print(f"Mismatch Breakdown        : {dict(mismatch_counts)}")
    print(f"Results Saved To          : {output_eval_path}")
    print(f"Summary Saved To          : {output_summary_path}")
    print("=" * 80)

    return summary, results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase 1 BIRD prototype evaluation.")
    parser.add_argument("--num_questions", type=int, default=50, help="Number of questions to evaluate (default: 50)")
    parser.add_argument(
        "--disable_llm_intent",
        action="store_true",
        help="Disable Gemini API and use deterministic intent analyzer",
    )
    args = parser.parse_args()

    run_phase1_evaluation(
        num_questions=args.num_questions,
        disable_llm_intent=args.disable_llm_intent,
    )
