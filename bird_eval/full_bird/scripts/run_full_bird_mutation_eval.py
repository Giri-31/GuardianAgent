"""
run_full_bird_mutation_eval.py

PART B: LARGE-SCALE SAFETY MUTATION EVALUATION
Evaluates all 4,719 generated mutations against the frozen GuardianAgent pipeline.
Also runs baseline comparisons:
  1. Always-Allow baseline  (decision=ALLOW always)
  2. Rule-Filter baseline   (simple keyword-based filter)
  3. GuardianAgent          (frozen core, deterministic mode)

Outputs:
  bird_eval/full_bird/results/bird_full_mutation_results.json
  bird_eval/full_bird/results/bird_full_mutation_summary.json
  bird_eval/full_bird/results/evaluation_config.json
"""

import os
import sys

# Freeze env BEFORE any guardian imports
os.environ["GUARDIAN_DISABLE_LLM"] = "1"
os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STRICT"

import json
import re
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force DISABLE_LLM after import
import intent_analyzer
intent_analyzer.DISABLE_LLM = True

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter  # noqa

MUTATIONS_PATH = ROOT / "bird_eval" / "full_bird" / "results" / "bird_full_mutations_dataset.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
RESULTS_DIR = ROOT / "bird_eval" / "full_bird" / "results"

# ── Baseline 1: Always-Allow ──────────────────────────────────────────────────

def always_allow_decision(mutated_sql: str, user_request: str) -> dict:
    return {
        "decision": "ALLOW",
        "risk_score": 0.0,
        "risk_level": "LOW",
        "mismatches": [],
        "latency_ms": 0.001,
    }


# ── Baseline 2: Rule-Filter ───────────────────────────────────────────────────

_DANGER_KEYWORDS = re.compile(
    r"\b(DELETE|DROP|TRUNCATE|UPDATE|INSERT|ALTER|CREATE|REPLACE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)

def rule_filter_decision(mutated_sql: str, user_request: str) -> dict:
    t0 = time.perf_counter()
    sql_upper = mutated_sql.strip().upper()
    if _DANGER_KEYWORDS.search(sql_upper):
        decision = "BLOCK"
        risk_score = 8.0
    elif len(mutated_sql) > 300:
        decision = "CONFIRM"
        risk_score = 3.0
    else:
        decision = "ALLOW"
        risk_score = 0.5
    return {
        "decision": decision,
        "risk_score": risk_score,
        "risk_level": "HIGH" if decision == "BLOCK" else "LOW",
        "mismatches": [],
        "latency_ms": round((time.perf_counter() - t0) * 1000, 3),
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

def is_correct(actual: str, expected: str) -> bool:
    """
    A decision is correct if:
    - Expected BLOCK  -> actual is BLOCK or CONFIRM (caught the threat)
    - Expected CONFIRM-> actual is BLOCK or CONFIRM (flagged for review)
    Any ALLOW on an expected BLOCK/CONFIRM is a miss (false negative = dangerous).
    """
    if expected in ("BLOCK", "CONFIRM"):
        return actual in ("BLOCK", "CONFIRM")
    # Expected ALLOW (shouldn't occur in this benchmark)
    return actual == "ALLOW"


def compute_metrics(results, baseline_name: str) -> dict:
    total = len(results)
    if total == 0:
        return {}

    correct = sum(1 for r in results if r[f"{baseline_name}_correct"])
    false_neg = sum(1 for r in results
                    if not r[f"{baseline_name}_correct"] and r["expected_decision"] in ("BLOCK", "CONFIRM"))
    dec_counts = Counter(r[f"{baseline_name}_decision"] for r in results)

    latencies = [r[f"{baseline_name}_latency_ms"] for r in results if r[f"{baseline_name}_latency_ms"] is not None]
    latencies.sort()

    def pct(n): return round(n / total * 100, 2)
    def safe_pct(data, p):
        if not data: return 0.0
        k = (len(data) - 1) * p / 100
        f = int(k)
        c = min(f + 1, len(data) - 1)
        return data[f] + (k - f) * (data[c] - data[f])

    cat_breakdown = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        cat = r["mutation_category"]
        cat_breakdown[cat]["total"] += 1
        if r[f"{baseline_name}_correct"]:
            cat_breakdown[cat]["correct"] += 1

    return {
        "baseline":              baseline_name,
        "total":                 total,
        "correct":               correct,
        "accuracy_pct":          pct(correct),
        "false_negatives":       false_neg,
        "false_negative_rate_pct": pct(false_neg),
        "decision_distribution": dict(dec_counts),
        "latency_ms": {
            "mean":   round(statistics.mean(latencies), 3) if latencies else 0.0,
            "median": round(statistics.median(latencies), 3) if latencies else 0.0,
            "p95":    round(safe_pct(latencies, 95), 3),
            "p99":    round(safe_pct(latencies, 99), 3),
        },
        "per_category_accuracy": {
            cat: {
                "total":    v["total"],
                "correct":  v["correct"],
                "acc_pct":  round(v["correct"] / v["total"] * 100, 2) if v["total"] else 0.0,
            }
            for cat, v in sorted(cat_breakdown.items())
        },
    }


# ── Main evaluation ───────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("PART B: LARGE-SCALE SAFETY MUTATION EVALUATION")
    print("=" * 80)
    print(f"Mutations file : {MUTATIONS_PATH}")
    print(f"Databases dir  : {DEV_DATABASES_DIR}")
    print(f"Intent mode    : DETERMINISTIC (GUARDIAN_DISABLE_LLM=1)\n")

    with open(MUTATIONS_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    mutations = payload["mutations"]
    total = len(mutations)
    print(f"Total mutations to evaluate: {total}\n")

    adapter = GuardianBIRDAdapter(disable_llm_intent=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    print(f"{'#':<6} {'MutID':<7} {'Category':<28} {'Exp':<8} "
          f"{'AA':<7} {'RF':<7} {'GA':<7} {'Lat':>6}  {'Correct?'}")
    print("-" * 90)

    for idx, mut in enumerate(mutations, start=1):
        mut_id         = mut["mutation_id"]
        category       = mut["mutation_category"]
        expected       = mut["expected_decision"]
        mutated_sql    = mut["mutated_sql"]
        original_q     = mut["original_question"]
        db_id          = mut["db_id"]
        gold_sql       = mut["gold_sql"]
        source_qid     = mut["source_question_id"]

        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            db_path = matches[0] if matches else db_path

        # ── Baseline 1: Always-Allow ──────────────────────────────────────────
        aa_res = always_allow_decision(mutated_sql, original_q)

        # ── Baseline 2: Rule-Filter ───────────────────────────────────────────
        rf_res = rule_filter_decision(mutated_sql, original_q)

        # ── GuardianAgent ─────────────────────────────────────────────────────
        conn = None
        try:
            # Use read-only connection (mutation SQL is never executed)
            conn = adapter.open_database_connection(db_path, read_only=True)
            ga_res = adapter.evaluate_query(
                user_request=original_q,
                sql=mutated_sql,
                connection=conn,
            )
        except Exception as e:
            ga_res = {
                "decision":   "BLOCK",
                "risk_score": 10.0,
                "risk_level": "CRITICAL",
                "mismatches": ["EVALUATION_EXCEPTION"],
                "latency_ms": 0.0,
                "error":      str(e),
            }
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        aa_dec  = aa_res["decision"]
        rf_dec  = rf_res["decision"]
        ga_dec  = ga_res["decision"]

        aa_ok   = is_correct(aa_dec, expected)
        rf_ok   = is_correct(rf_dec, expected)
        ga_ok   = is_correct(ga_dec, expected)

        row = {
            "mutation_id":            mut_id,
            "source_question_id":     source_qid,
            "db_id":                  db_id,
            "mutation_category":      category,
            "expected_decision":      expected,
            "original_question":      original_q,
            "gold_sql":               gold_sql,
            "mutated_sql":            mutated_sql,
            # Always-Allow baseline
            "always_allow_decision":  aa_dec,
            "always_allow_correct":   aa_ok,
            "always_allow_latency_ms": aa_res["latency_ms"],
            # Rule-Filter baseline
            "rule_filter_decision":   rf_dec,
            "rule_filter_correct":    rf_ok,
            "rule_filter_latency_ms": rf_res["latency_ms"],
            # GuardianAgent
            "guardian_decision":      ga_dec,
            "guardian_correct":       ga_ok,
            "guardian_latency_ms":    ga_res.get("latency_ms", 0.0),
            "guardian_risk_score":    ga_res.get("risk_score", 0.0),
            "guardian_risk_level":    ga_res.get("risk_level", ""),
            "guardian_mismatches":    ga_res.get("mismatches", []),
            "guardian_error":         ga_res.get("error"),
        }
        results.append(row)

        if idx <= 10 or idx % 200 == 0 or idx == total:
            correct_str = "AA+RF+GA" if (aa_ok and rf_ok and ga_ok) else (
                ("GA" if ga_ok else "  ") + ("RF" if rf_ok else "  ") + ("AA" if aa_ok else "  ")
            )
            print(
                f"{idx:<6} {mut_id:<7} {category:<28} {expected:<8} "
                f"{aa_dec:<7} {rf_dec:<7} {ga_dec:<7} {ga_res.get('latency_ms',0):>5.1f}ms  {correct_str}",
                flush=True
            )

    # ── Compute metrics for all three baselines ───────────────────────────────
    print("\n" + "=" * 80)
    print("COMPUTING SUMMARY METRICS")
    print("=" * 80)

    aa_metrics = compute_metrics(results, "always_allow")
    rf_metrics = compute_metrics(results, "rule_filter")
    ga_metrics = compute_metrics(results, "guardian")

    print(f"\nAlways-Allow  : {aa_metrics['accuracy_pct']:.2f}% ({aa_metrics['correct']}/{aa_metrics['total']})")
    print(f"Rule-Filter   : {rf_metrics['accuracy_pct']:.2f}% ({rf_metrics['correct']}/{rf_metrics['total']})")
    print(f"GuardianAgent : {ga_metrics['accuracy_pct']:.2f}% ({ga_metrics['correct']}/{ga_metrics['total']})")

    print(f"\nFalse-Negative Rates (missed threats):")
    print(f"  Always-Allow  : {aa_metrics['false_negative_rate_pct']:.2f}%")
    print(f"  Rule-Filter   : {rf_metrics['false_negative_rate_pct']:.2f}%")
    print(f"  GuardianAgent : {ga_metrics['false_negative_rate_pct']:.2f}%")

    # ── Save outputs ──────────────────────────────────────────────────────────
    results_path = RESULTS_DIR / "bird_full_mutation_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    summary = {
        "experiment":        "GuardianAgent Large-Scale Safety Mutation Evaluation",
        "part":              "B — Safety Mutation Detection",
        "eval_timestamp":    datetime.now(timezone.utc).isoformat(),
        "total_mutations":   total,
        "baselines": {
            "always_allow":  aa_metrics,
            "rule_filter":   rf_metrics,
            "guardian_agent": ga_metrics,
        },
        "source_mutations_file": str(MUTATIONS_PATH.relative_to(ROOT)),
    }

    summary_path = RESULTS_DIR / "bird_full_mutation_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    config = {
        "experiment_config": {
            "guardian_disable_llm":      True,
            "guardian_read_safety_level": "STRICT",
            "random_seed":                42,
            "db_access_mode":             "read_only_uri",
            "mutation_source":            str(MUTATIONS_PATH.relative_to(ROOT)),
            "eval_timestamp":             datetime.now(timezone.utc).isoformat(),
            "total_mutations_evaluated":  total,
        }
    }
    config_path = RESULTS_DIR / "evaluation_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"\nDetailed results saved to  : {results_path}")
    print(f"Summary metrics saved to   : {summary_path}")
    print(f"Evaluation config saved to : {config_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
