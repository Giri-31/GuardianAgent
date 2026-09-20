"""
large_ablation_runner.py

GuardianAgent — Final Large-Scale Component Ablation Runner
============================================================

Evaluates GuardianAgent under 5 ablation configurations on the
1,500-case independent V1 held-out benchmark:

  1. FULL           – Complete GuardianAgent safety pipeline
  2. NO_INTENT_SQL  – Without Intent-SQL consistency checker
  3. NO_SCOPE       – Without Scope analysis (unknown scope)
  4. NO_IMPACT      – Without Database impact analysis (neutral LOW impact)
  5. NO_INTENT      – SQL-only baseline (no natural language intent reasoning)

OUTPUTS:
  benchmark/large_ablation_results.json
  benchmark/large_benchmark_results.json  (updated with ablation section)
"""

import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# PATH SETUP
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guardian import guardian_check, analyze_impact, analyze_scope_safely
from sql_analyzer import analyze_sql
from intent_sql_checker import check_intent_sql
from risk_engine import calculate_risk

# Try importing sklearn, else use robust pure Python fallback
try:
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        precision_recall_fscore_support,
    )
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

# ============================================================
# PATHS
# ============================================================

V1_DATASET_PATH = ROOT / "benchmark" / "heldout_v1_1500_dataset.json"
V2_DATASET_PATH = ROOT / "benchmark" / "adversarial_v2_1500_dataset.json"
ABLATION_RESULTS_PATH = ROOT / "benchmark" / "large_ablation_results.json"
COMBINED_RESULTS_PATH = ROOT / "benchmark" / "large_benchmark_results.json"

DECISIONS = ["ALLOW", "CONFIRM", "BLOCK"]
CONFIGURATIONS = ["FULL", "NO_INTENT_SQL", "NO_SCOPE", "NO_IMPACT", "NO_INTENT"]


# ============================================================
# FALLBACK METRICS
# ============================================================

def _compute_metrics_py(y_true, y_pred):
    n = len(y_true)
    correct = sum(1 for yt, yp in zip(y_true, y_pred) if yt == yp)
    accuracy = correct / n if n else 0.0

    matrix = [[0 for _ in DECISIONS] for _ in DECISIONS]
    idx_map = {d: i for i, d in enumerate(DECISIONS)}
    for yt, yp in zip(y_true, y_pred):
        if yt in idx_map and yp in idx_map:
            matrix[idx_map[yt]][idx_map[yp]] += 1

    per_class = {}
    f1s, precs, recs = [], [], []
    for i, label in enumerate(DECISIONS):
        tp = matrix[i][i]
        fp = sum(matrix[r][i] for r in range(len(DECISIONS)) if r != i)
        fn = sum(matrix[i][c] for c in range(len(DECISIONS)) if c != i)
        sup = sum(matrix[i])

        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

        precs.append(prec)
        recs.append(rec)
        f1s.append(f1)
        per_class[label] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": sup,
        }

    return {
        "accuracy": round(accuracy * 100, 2),
        "macro_f1": round(sum(f1s) / len(f1s), 4),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": DECISIONS,
            "matrix": matrix,
        },
    }


def compute_metrics(y_true, y_pred):
    if HAS_SKLEARN:
        acc = accuracy_score(y_true, y_pred)
        p, r, f1, sup = precision_recall_fscore_support(
            y_true, y_pred, labels=DECISIONS, zero_division=0
        )
        mat = confusion_matrix(y_true, y_pred, labels=DECISIONS)
        per_class = {}
        for i, label in enumerate(DECISIONS):
            per_class[label] = {
                "precision": round(float(p[i]), 4),
                "recall": round(float(r[i]), 4),
                "f1": round(float(f1[i]), 4),
                "support": int(sup[i]),
            }
        return {
            "accuracy": round(float(acc) * 100, 2),
            "macro_f1": round(float(f1.mean()), 4),
            "per_class": per_class,
            "confusion_matrix": {
                "labels": DECISIONS,
                "matrix": mat.tolist(),
            },
        }
    return _compute_metrics_py(y_true, y_pred)


def compute_safety_metrics(y_true, y_pred):
    dangerous_not_blocked = 0
    safe_incorrectly_blocked = 0
    for actual, pred in zip(y_true, y_pred):
        if actual == "BLOCK" and pred != "BLOCK":
            dangerous_not_blocked += 1
        if actual == "ALLOW" and pred == "BLOCK":
            safe_incorrectly_blocked += 1
    return {
        "dangerous_not_blocked": dangerous_not_blocked,
        "safe_incorrectly_blocked": safe_incorrectly_blocked,
    }


def compute_category_metrics(cases, preds):
    cats = defaultdict(lambda: {"correct": 0, "total": 0})
    for case, pred in zip(cases, preds):
        c = case["category"]
        cats[c]["total"] += 1
        if pred == case["expected_decision"]:
            cats[c]["correct"] += 1
    output = {}
    for c in sorted(cats):
        tot = cats[c]["total"]
        cor = cats[c]["correct"]
        output[c] = {
            "correct": cor,
            "total": tot,
            "accuracy": round((cor / tot) * 100, 2) if tot else 0.0,
        }
    return output


# ============================================================
# ABLATED EVALUATION
# ============================================================

def ablated_guardian(case, mode):
    request = case["user_request"]
    sql = case["generated_sql"]
    intent = case["ground_truth_intent"]

    # 1. FULL PIPELINE
    if mode == "FULL":
        result = guardian_check(request, sql, known_intent=intent)
        return result["risk"]["decision"]

    sql_info = analyze_sql(sql)
    full_result = guardian_check(request, sql, known_intent=intent)
    scope = full_result["scope"]
    impact = full_result["impact"]

    # 2. NO INTENT-SQL CHECKER
    if mode == "NO_INTENT_SQL":
        neutral_intent_sql = {"status": "MATCH", "mismatches": []}
        risk = calculate_risk(intent, sql_info, scope, impact, neutral_intent_sql)
        return risk["decision"]

    # 3. NO SCOPE ANALYSIS
    if mode == "NO_SCOPE":
        intent_sql = check_intent_sql(intent, sql)
        # Remove SCOPE_MISMATCH
        filtered_mismatches = [m for m in intent_sql.get("mismatches", []) if m != "SCOPE_MISMATCH"]
        intent_sql_no_scope = {
            "status": "MISMATCH" if filtered_mismatches else "MATCH",
            "mismatches": filtered_mismatches,
            "match": len(filtered_mismatches) == 0,
        }
        risk = calculate_risk(intent, sql_info, "UNKNOWN", impact, intent_sql_no_scope)
        return risk["decision"]

    # 4. NO DATABASE IMPACT ANALYSIS
    if mode == "NO_IMPACT":
        intent_sql = check_intent_sql(intent, sql)
        neutral_impact = {"impact_type": "UNKNOWN", "risk_level": "LOW"}
        risk = calculate_risk(intent, sql_info, scope, neutral_impact, intent_sql)
        return risk["decision"]

    # 5. NO INTENT (SQL-ONLY)
    if mode == "NO_INTENT":
        intent_without_semantics = {
            "operation": sql_info.get("operation", "UNKNOWN"),
            "target": "unknown",
            "field": "unknown",
            "value": "unknown",
            "scope": "unknown",
        }
        neutral_intent_sql = {"status": "MATCH", "mismatches": [], "match": True}
        risk = calculate_risk(intent_without_semantics, sql_info, scope, impact, neutral_intent_sql)
        return risk["decision"]

    raise ValueError(f"Unknown ablation mode: {mode}")


# ============================================================
# RUN ABLATION BENCHMARK
# ============================================================

def run_ablation(dataset_path, dataset_name):
    print("=" * 70)
    print(f"GUARDIANAGENT COMPONENT ABLATION: {dataset_name}")
    print("=" * 70)

    with open(dataset_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"Dataset cases   : {len(cases)}")
    y_true = [c["expected_decision"] for c in cases]

    results = {
        "experiment": f"GuardianAgent Component Ablation ({dataset_name})",
        "dataset": str(dataset_path),
        "total_cases": len(cases),
        "intent_mode": "GROUND-TRUTH",
        "sql_execution": False,
        "configurations": {},
    }

    for config in CONFIGURATIONS:
        print(f"\nRunning configuration: {config}...")
        preds = []
        latencies = []

        for case in cases:
            t0 = time.perf_counter()
            pred = ablated_guardian(case, config)
            el = (time.perf_counter() - t0) * 1000
            preds.append(pred)
            latencies.append(el)

        metrics = compute_metrics(y_true, preds)
        safety = compute_safety_metrics(y_true, preds)
        cat_metrics = compute_category_metrics(cases, preds)

        latencies.sort()
        lat_stats = {
            "mean": round(sum(latencies) / len(latencies), 4),
            "median": round(latencies[len(latencies) // 2], 4),
            "minimum": round(min(latencies), 4),
            "maximum": round(max(latencies), 4),
        }

        results["configurations"][config] = {
            "accuracy": metrics["accuracy"],
            "macro_f1": metrics["macro_f1"],
            "per_class": metrics["per_class"],
            "confusion_matrix": metrics["confusion_matrix"],
            "category_results": cat_metrics,
            "safety": safety,
            "latency_ms": lat_stats,
        }

        print(f"  Accuracy : {metrics['accuracy']:.2f}% | Macro F1: {metrics['macro_f1']:.4f}")
        print(f"  Dangerous Not Blocked: {safety['dangerous_not_blocked']} | Safe False-Blocked: {safety['safe_incorrectly_blocked']}")

    # Print comparative summary table
    print("\n" + "=" * 70)
    print(f"ABLATION COMPARATIVE SUMMARY ({dataset_name})")
    print("=" * 70)
    print(f"{'Configuration':<16} {'Accuracy':>10} {'Macro-F1':>10} {'Unsafe Miss':>14} {'False-Block':>14}")
    print("-" * 70)
    for config in CONFIGURATIONS:
        cfg = results["configurations"][config]
        acc_str = f"{cfg['accuracy']:.2f}%"
        f1_str = f"{cfg['macro_f1']:.4f}"
        d_nb = str(cfg["safety"]["dangerous_not_blocked"])
        s_ib = str(cfg["safety"]["safe_incorrectly_blocked"])
        print(f"{config:<16} {acc_str:>10} {f1_str:>10} {d_nb:>14} {s_ib:>14}")
    print("=" * 70)

    return results


def main():
    v1_results = run_ablation(V1_DATASET_PATH, "V1_Independent_1500")
    v2_results = run_ablation(V2_DATASET_PATH, "V2_Adversarial_1500")

    combined_ablation = {
        "v1_independent_1500": v1_results,
        "v2_adversarial_1500": v2_results,
    }

    # Save ablation results
    with open(ABLATION_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(combined_ablation, f, indent=2)
    print(f"\nAblation results saved to: {ABLATION_RESULTS_PATH}")

    # Update large_benchmark_results.json
    combined = {}
    if COMBINED_RESULTS_PATH.exists():
        with open(COMBINED_RESULTS_PATH, "r", encoding="utf-8") as f:
            combined = json.load(f)

    combined["ablation_study_v1"] = {
        "configurations": {
            config: {
                "accuracy": v1_results["configurations"][config]["accuracy"],
                "macro_f1": v1_results["configurations"][config]["macro_f1"],
                "dangerous_not_blocked": v1_results["configurations"][config]["safety"]["dangerous_not_blocked"],
                "safe_incorrectly_blocked": v1_results["configurations"][config]["safety"]["safe_incorrectly_blocked"],
            }
            for config in CONFIGURATIONS
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    combined["ablation_study_v2"] = {
        "configurations": {
            config: {
                "accuracy": v2_results["configurations"][config]["accuracy"],
                "macro_f1": v2_results["configurations"][config]["macro_f1"],
                "dangerous_not_blocked": v2_results["configurations"][config]["safety"]["dangerous_not_blocked"],
                "safe_incorrectly_blocked": v2_results["configurations"][config]["safety"]["safe_incorrectly_blocked"],
            }
            for config in CONFIGURATIONS
        },
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(COMBINED_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2)
    print(f"Updated combined results: {COMBINED_RESULTS_PATH}")


if __name__ == "__main__":
    main()

