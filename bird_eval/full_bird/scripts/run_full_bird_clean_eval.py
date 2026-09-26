"""
run_full_bird_clean_eval.py

PART A: FULL CLEAN BIRD EVALUATION
Evaluates legitimate BIRD question + gold SQL pairs against the frozen GuardianAgent.

Features:
- Evaluates all 500 clean source queries (reporting both Overall 500 and Frozen 400 partition).
- Evaluates legitimate queries safely in read-only mode.
- Verifies ground-truth execution against the official BIRD SQLite databases.
- Computes detailed latency statistics (mean, median, P95, P99).
- Measures legitimate-query false-block rate and human-confirmation rate.
- Outputs detailed case records and aggregated summary JSONs.

Outputs:
  bird_eval/full_bird/results/bird_full_clean_results.json
  bird_eval/full_bird/results/bird_full_clean_summary.json
"""

import os
import sys

# Ensure reproducible deterministic mode before any guardian imports
os.environ["GUARDIAN_DISABLE_LLM"] = "1"
os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STRICT"

import argparse
import json
import sqlite3
import statistics
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import intent_analyzer
intent_analyzer.DISABLE_LLM = True

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DATA_PATH = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "mini_dev_sqlite.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
RESULTS_DIR = ROOT / "bird_eval" / "full_bird" / "results"


def percentile(data, p):
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c < len(data):
        return data[f] + (k - f) * (data[c] - data[f])
    else:
        return data[f]


def run_clean_evaluation(disable_llm_intent: bool = True):
    print("=" * 80)
    print("PART A: FULL CLEAN BIRD EVALUATION (LEGITIMATE QUERIES)")
    print("=" * 80)
    print(f"Dataset Path : {DATA_PATH}")
    print(f"Databases Dir: {DEV_DATABASES_DIR}")
    print(f"Intent Mode  : {'Deterministic (Frozen Baseline)' if disable_llm_intent else 'LLM'}\n")

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        queries = json.load(f)

    total_queries = len(queries)
    print(f"Total legitimate queries to evaluate: {total_queries}\n")

    adapter = GuardianBIRDAdapter(disable_llm_intent=disable_llm_intent)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    latencies = []
    decision_counts = Counter()
    exec_success_count = 0
    exec_failure_count = 0
    db_stats = defaultdict(lambda: {
        "total": 0,
        "ALLOW": 0,
        "CONFIRM": 0,
        "BLOCK": 0,
        "exec_success": 0,
        "exec_failed": 0,
        "latencies": [],
    })

    print(f"{'#':<4} {'QID':<6} {'Database':<23} {'Exec':<8} {'Guardian':<10} {'Risk':<6} {'Latency':<9} {'Mismatches':<20}")
    print("-" * 95)

    start_eval_time = time.perf_counter()

    for idx, item in enumerate(queries, start=1):
        qid = item["question_id"]
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["SQL"].strip()
        difficulty = item.get("difficulty", "unknown")

        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            if matches:
                db_path = matches[0]

        # 1. Ground truth execution check (safe read-only, 10s timeout)
        EXEC_TIMEOUT_SEC = 10
        exec_ok = False
        exec_error = None
        conn = None
        _exec_result = {"ok": False, "err": None, "conn": None}

        def _try_exec():
            try:
                c = adapter.open_database_connection(db_path, read_only=True)
                c.execute("PRAGMA busy_timeout = 8000")
                cur = c.cursor()
                cur.execute(gold_sql)
                cur.fetchone()
                _exec_result["ok"] = True
                _exec_result["conn"] = c
            except Exception as ex:
                _exec_result["err"] = str(ex)
                try:
                    if c:
                        c.close()
                except Exception:
                    pass

        t = threading.Thread(target=_try_exec, daemon=True)
        t.start()
        t.join(timeout=EXEC_TIMEOUT_SEC)
        if t.is_alive():
            # Query timed out; record as failure, continue
            exec_ok = False
            exec_error = f"EXEC_TIMEOUT>{EXEC_TIMEOUT_SEC}s"
            exec_failure_count += 1
            db_stats[db_id]["exec_failed"] += 1
            conn = None
        elif _exec_result["ok"]:
            exec_ok = True
            exec_success_count += 1
            db_stats[db_id]["exec_success"] += 1
            conn = _exec_result["conn"]
        else:
            exec_ok = False
            exec_error = _exec_result["err"]
            exec_failure_count += 1
            db_stats[db_id]["exec_failed"] += 1

        # 2. GuardianAgent evaluation
        try:
            t0 = time.perf_counter()
            guardian_res = adapter.evaluate_query(
                user_request=question,
                sql=gold_sql,
                connection=conn,
            )
            t_elapsed_ms = (time.perf_counter() - t0) * 1000
        except Exception as e:
            guardian_res = {
                "decision": "BLOCK",
                "risk_score": 10.0,
                "risk_level": "CRITICAL",
                "mismatches": ["EVALUATION_EXCEPTION"],
                "latency_ms": 0.0,
                "error": str(e),
            }
            t_elapsed_ms = 0.0
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        actual_decision = guardian_res["decision"]
        risk_score = guardian_res["risk_score"]
        mismatches = guardian_res.get("mismatches", [])
        latency_ms = guardian_res.get("latency_ms", t_elapsed_ms)

        decision_counts[actual_decision] += 1
        latencies.append(latency_ms)

        db_stats[db_id]["total"] += 1
        db_stats[db_id][actual_decision] += 1
        db_stats[db_id]["latencies"].append(latency_ms)

        exec_str = "OK" if exec_ok else "FAIL"
        mism_str = str(mismatches) if mismatches else "[]"
        if len(mism_str) > 20:
            mism_str = mism_str[:17] + "..."

        if idx <= 10 or idx % 25 == 0 or idx == total_queries:
            print(
                f"{idx:<4} {qid:<6} {db_id[:22]:<23} {exec_str:<8} {actual_decision:<10} "
                f"{risk_score:<6.2f} {latency_ms:<6.2f}ms {mism_str:<20}",
                flush=True
            )

        results.append({
            "index": idx,
            "question_id": qid,
            "db_id": db_id,
            "difficulty": difficulty,
            "question": question,
            "gold_sql": gold_sql,
            "exec_success": exec_ok,
            "exec_error": exec_error,
            "guardian_decision": actual_decision,
            "risk_score": risk_score,
            "risk_level": guardian_res.get("risk_level"),
            "mismatches": mismatches,
            "latency_ms": round(latency_ms, 3),
            "is_frozen_split": (idx > 100),
        })

    total_eval_seconds = time.perf_counter() - start_eval_time

    # Latency distribution calculations
    sorted_latencies = sorted(latencies)
    mean_lat = statistics.mean(latencies) if latencies else 0.0
    median_lat = statistics.median(latencies) if latencies else 0.0
    p95_lat = percentile(sorted_latencies, 95)
    p99_lat = percentile(sorted_latencies, 99)

    allow_count = decision_counts["ALLOW"]
    confirm_count = decision_counts["CONFIRM"]
    block_count = decision_counts["BLOCK"]

    false_block_rate = (block_count / total_queries * 100) if total_queries > 0 else 0.0
    confirm_rate = (confirm_count / total_queries * 100) if total_queries > 0 else 0.0
    allow_rate = (allow_count / total_queries * 100) if total_queries > 0 else 0.0

    print("\n" + "=" * 80)
    print("PART A: FULL CLEAN EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Source Queries Evaluated : {total_queries}")
    print(f"Execution Success Rate         : {exec_success_count}/{total_queries} ({exec_success_count/total_queries*100:.2f}%)")
    print(f"Execution Failures (Gold SQL)  : {exec_failure_count}")
    print()
    print("Guardian Decision Distribution on Legitimate Queries:")
    print(f"  ALLOW   : {allow_count:<4} ({allow_rate:.2f}%)")
    print(f"  CONFIRM : {confirm_count:<4} ({confirm_rate:.2f}%)")
    print(f"  BLOCK   : {block_count:<4} ({false_block_rate:.2f}%) [False-Block Rate]")
    print()
    print("Latency Profile (Per Query):")
    print(f"  Mean Latency   : {mean_lat:.3f} ms")
    print(f"  Median Latency : {median_lat:.3f} ms")
    print(f"  P95 Latency    : {p95_lat:.3f} ms")
    print(f"  P99 Latency    : {p99_lat:.3f} ms")
    print(f"  Total Run Time : {total_eval_seconds:.2f} s")
    print()
    print("Per-Database Breakdown:")
    print(f"{'Database':<26} {'Total':<6} {'ALLOW %':<10} {'CONFIRM %':<11} {'BLOCK %':<10} {'Mean Lat':<10}")
    print("-" * 75)

    per_db_summary = {}
    for db in sorted(db_stats.keys()):
        st = db_stats[db]
        tot = st["total"]
        a_pct = (st["ALLOW"] / tot * 100) if tot > 0 else 0.0
        c_pct = (st["CONFIRM"] / tot * 100) if tot > 0 else 0.0
        b_pct = (st["BLOCK"] / tot * 100) if tot > 0 else 0.0
        m_lat = statistics.mean(st["latencies"]) if st["latencies"] else 0.0
        print(f"{db:<26} {tot:<6} {a_pct:<9.1f}% {c_pct:<10.1f}% {b_pct:<9.1f}% {m_lat:<8.3f} ms")
        per_db_summary[db] = {
            "total": tot,
            "allow_count": st["ALLOW"],
            "allow_pct": round(a_pct, 2),
            "confirm_count": st["CONFIRM"],
            "confirm_pct": round(c_pct, 2),
            "block_count": st["BLOCK"],
            "block_pct": round(b_pct, 2),
            "exec_success": st["exec_success"],
            "mean_latency_ms": round(m_lat, 3),
        }

    # Separate summary for the 400 Frozen Split
    frozen_results = [r for r in results if r["is_frozen_split"]]
    frozen_lat = [r["latency_ms"] for r in frozen_results]
    frozen_decisions = Counter(r["guardian_decision"] for r in frozen_results)
    frozen_total = len(frozen_results)

    summary_payload = {
        "metadata": {
            "evaluation_phase": "Part A: Full Clean Legitimate-Query Evaluation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_dataset": "birdsql/bird_mini_dev (mini_dev_sqlite.json)",
            "total_queries_evaluated": total_queries,
            "intent_mode": "deterministic",
        },
        "overall_clean_evaluation": {
            "total_queries": total_queries,
            "allow_count": allow_count,
            "allow_pct": round(allow_rate, 2),
            "confirm_count": confirm_count,
            "confirm_pct": round(confirm_rate, 2),
            "block_count": block_count,
            "false_block_rate_pct": round(false_block_rate, 2),
            "exec_success_count": exec_success_count,
            "exec_failure_count": exec_failure_count,
            "exec_success_rate_pct": round(exec_success_count / total_queries * 100, 2),
            "latency_metrics_ms": {
                "mean": round(mean_lat, 3),
                "median": round(median_lat, 3),
                "p95": round(p95_lat, 3),
                "p99": round(p99_lat, 3),
            },
        },
        "frozen_partition_clean_evaluation": {
            "total_queries": frozen_total,
            "allow_count": frozen_decisions["ALLOW"],
            "allow_pct": round(frozen_decisions["ALLOW"] / frozen_total * 100, 2) if frozen_total else 0.0,
            "confirm_count": frozen_decisions["CONFIRM"],
            "confirm_pct": round(frozen_decisions["CONFIRM"] / frozen_total * 100, 2) if frozen_total else 0.0,
            "block_count": frozen_decisions["BLOCK"],
            "false_block_rate_pct": round(frozen_decisions["BLOCK"] / frozen_total * 100, 2) if frozen_total else 0.0,
            "mean_latency_ms": round(statistics.mean(frozen_lat), 3) if frozen_lat else 0.0,
        },
        "per_database_breakdown": per_db_summary,
    }

    results_file = RESULTS_DIR / "bird_full_clean_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    summary_file = RESULTS_DIR / "bird_full_clean_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, indent=2)

    print(f"\nDetailed clean results saved to : {results_file}")
    print(f"Summary metrics saved to        : {summary_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--disable_llm_intent", action="store_true", default=True)
    args = parser.parse_args()
    run_clean_evaluation(disable_llm_intent=args.disable_llm_intent)
