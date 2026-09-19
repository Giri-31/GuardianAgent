"""
evaluate_dbbench_saved.py

Offline evaluation of saved DBBench Stage-2 results.

Reads benchmark/dbbench_stage2_results.json and reports:
  - How many tasks were completed vs. errored
  - For completed tasks: GuardianAgent decision distribution
  - Accuracy metrics (when ground-truth labels are available)

Usage::

    python benchmark/evaluate_dbbench_saved.py

No API calls are made; all data comes from the saved JSON file.
"""

import json
import os
import sys


# ============================================================
# Paths
# ============================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULTS_FILE = os.path.join(
    ROOT,
    "benchmark",
    "llm_guardian_full_results.json",
)


# ============================================================
# Load results
# ============================================================

def load_results():

    if not os.path.isfile(RESULTS_FILE):
        print(f"[ERROR] Results file not found: {RESULTS_FILE}")
        sys.exit(1)

    with open(RESULTS_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ============================================================
# Evaluate
# ============================================================

def evaluate(results):

    total = len(results)

    completed = [
        r for r in results
        if r.get("status") == "COMPLETED" or "guardian_decision" in r
    ]
    errored = [
        r for r in results
        if r.get("status") not in (None, "COMPLETED") and "guardian_decision" not in r
    ]

    print()
    print("=" * 70)
    print("DBBENCH STAGE-2 SAVED RESULTS EVALUATION")
    print("=" * 70)

    print(f"\nTotal records   : {total}")
    print(f"Completed       : {len(completed)}")
    print(f"Errored / Skip  : {len(errored)}")

    # --------------------------------------------------------
    # Error breakdown
    # --------------------------------------------------------

    if errored:
        print()
        print("-" * 40)
        print("Error status breakdown:")
        breakdown = {}
        for r in errored:
            key = r.get("status", "UNKNOWN")
            breakdown[key] = breakdown.get(key, 0) + 1
        for status, count in sorted(breakdown.items()):
            print(f"  {status:<30} : {count}")

    if not completed:
        print("\n[WARN] No completed results to evaluate.")
        return

    # --------------------------------------------------------
    # Guardian decision distribution
    # --------------------------------------------------------

    print()
    print("-" * 40)
    print("Guardian decision distribution (completed):")
    decisions = {}
    for r in completed:
        decision = str(r.get("guardian_decision") or "None")
        decisions[decision] = decisions.get(decision, 0) + 1
    for decision, count in sorted(decisions.items(), key=lambda x: x[0]):
        pct = 100.0 * count / len(completed)
        print(f"  {decision:<20} : {count:>4}  ({pct:5.1f}%)")

    # --------------------------------------------------------
    # Risk level distribution
    # --------------------------------------------------------

    print()
    print("-" * 40)
    print("Guardian risk distribution (completed):")
    risks = {}
    for r in completed:
        risk = str(r.get("risk_level") or r.get("guardian_risk") or "None")
        risks[risk] = risks.get(risk, 0) + 1
    for risk, count in sorted(risks.items(), key=lambda x: x[0]):
        pct = 100.0 * count / len(completed)
        print(f"  {risk:<20} : {count:>4}  ({pct:5.1f}%)")

    # --------------------------------------------------------
    # SQL correctness (when available)
    # --------------------------------------------------------

    sql_correct_known = []
    for r in completed:
        if r.get("sql_correct") is not None:
            sql_correct_known.append(r.get("sql_correct"))
        elif "sql_evaluation" in r and r["sql_evaluation"].get("status") == "EVALUATED":
            sql_correct_known.append(r["sql_evaluation"].get("correct"))

    if sql_correct_known:
        correct_count = sum(1 for c in sql_correct_known if c is True)
        print()
        print("-" * 40)
        print("SQL correctness (subset with evaluated labels):")
        pct = 100.0 * correct_count / len(sql_correct_known)
        print(
            f"  Correct: {correct_count} / {len(sql_correct_known)} "
            f"({pct:.1f}%)"
        )

    # --------------------------------------------------------
    # Latency
    # --------------------------------------------------------

    latencies = [
        r.get("guardian_latency_ms")
        for r in completed
        if r.get("guardian_latency_ms") is not None
    ]

    if latencies:
        avg_ms = sum(latencies) / len(latencies)
        print()
        print("-" * 40)
        print("Guardian latency (completed):")
        print(f"  Average : {avg_ms:.0f} ms")
        print(f"  Min     : {min(latencies):.0f} ms")
        print(f"  Max     : {max(latencies):.0f} ms")

    print()
    print("=" * 70)


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    results = load_results()
    evaluate(results)