"""
large_v2_runner.py

GuardianAgent — Final Large-Scale V2 Adversarial Evaluation Runner
===================================================================

Evaluates GuardianAgent on the 1,500-case adversarial benchmark.

IMPORTANT:
- GuardianAgent implementation is FROZEN.
- Ground-truth intent is supplied (no Gemini API calls).
- SQL is NEVER executed.
- Dataset loaded from adversarial_v2_1500_dataset.json (pre-frozen).

OUTPUTS:
  benchmark/large_v2_results.json
  benchmark/large_benchmark_results.json  (updated with V2 section)
"""

import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guardian import guardian_check  # noqa: E402

DATASET_PATH = ROOT / "benchmark" / "adversarial_v2_1500_dataset.json"
RESULTS_PATH = ROOT / "benchmark" / "large_v2_results.json"
COMBINED_PATH = ROOT / "benchmark" / "large_benchmark_results.json"

DECISIONS = ["ALLOW", "CONFIRM", "BLOCK"]


def load_dataset():
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"V2 dataset not found: {DATASET_PATH}")
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_metrics(y_true, y_pred):
    accuracy = accuracy_score(y_true, y_pred)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=DECISIONS, zero_division=0
    )
    matrix = confusion_matrix(y_true, y_pred, labels=DECISIONS)
    per_class = {}
    for i, label in enumerate(DECISIONS):
        per_class[label] = {
            "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4),
            "f1": round(float(f1[i]), 4),
            "support": int(support[i]),
        }
    return {
        "accuracy": round(float(accuracy), 4),
        "accuracy_pct": round(float(accuracy) * 100, 2),
        "macro_precision": round(float(precision.mean()), 4),
        "macro_recall": round(float(recall.mean()), 4),
        "macro_f1": round(float(f1.mean()), 4),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": DECISIONS,
            "matrix": matrix.tolist(),
        },
    }


def compute_confidence_interval(accuracy, n, z=1.96):
    p = accuracy
    denominator = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denominator
    margin = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denominator
    return {
        "lower": round(max(0.0, center - margin), 4),
        "upper": round(min(1.0, center + margin), 4),
        "confidence_level": "95%",
        "method": "Wilson score interval",
    }


def compute_safety_metrics(y_true, y_pred):
    unsafe_miss = 0
    unsafe_allowed = 0
    unsafe_confirmed = 0
    safe_false_block = 0
    safe_false_confirm = 0
    total_dangerous = 0
    total_safe = 0

    for actual, predicted in zip(y_true, y_pred):
        if actual == "BLOCK":
            total_dangerous += 1
            if predicted != "BLOCK":
                unsafe_miss += 1
            if predicted == "ALLOW":
                unsafe_allowed += 1
            if predicted == "CONFIRM":
                unsafe_confirmed += 1
        if actual == "ALLOW":
            total_safe += 1
            if predicted == "BLOCK":
                safe_false_block += 1
            if predicted == "CONFIRM":
                safe_false_confirm += 1

    return {
        "total_dangerous_cases": total_dangerous,
        "total_safe_cases": total_safe,
        "unsafe_miss_count": unsafe_miss,
        "unsafe_miss_rate": round(unsafe_miss / total_dangerous, 4) if total_dangerous else 0.0,
        "unsafe_allowed_count": unsafe_allowed,
        "unsafe_confirmed_count": unsafe_confirmed,
        "safe_false_block_count": safe_false_block,
        "safe_false_block_rate": round(safe_false_block / total_safe, 4) if total_safe else 0.0,
        "safe_false_confirm_count": safe_false_confirm,
    }


def compute_latency_stats(latencies):
    n = len(latencies)
    if not n:
        return {}
    s = sorted(latencies)
    mean = sum(latencies) / n
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    variance = sum((x - mean) ** 2 for x in latencies) / n
    std = math.sqrt(variance)
    p95_idx = max(0, int(math.ceil(0.95 * n)) - 1)
    p99_idx = max(0, int(math.ceil(0.99 * n)) - 1)
    return {
        "mean_ms": round(mean, 4),
        "median_ms": round(median, 4),
        "std_ms": round(std, 4),
        "p95_ms": round(s[p95_idx], 4),
        "p99_ms": round(s[p99_idx], 4),
        "min_ms": round(s[0], 4),
        "max_ms": round(s[-1], 4),
        "n": n,
    }


def compute_category_metrics(results):
    cat = defaultdict(lambda: {"total": 0, "correct": 0,
                               "y_true": [], "y_pred": []})
    for r in results:
        c = r["category"]
        cat[c]["total"] += 1
        if r["correct"]:
            cat[c]["correct"] += 1
        cat[c]["y_true"].append(r["expected_decision"])
        cat[c]["y_pred"].append(r["predicted_decision"])

    output = {}
    for c in sorted(cat):
        total = cat[c]["total"]
        correct = cat[c]["correct"]
        acc = correct / total if total else 0
        try:
            p, r_v, f, _ = precision_recall_fscore_support(
                cat[c]["y_true"], cat[c]["y_pred"],
                labels=DECISIONS, average="macro", zero_division=0
            )
            precision = round(float(p), 4)
            recall = round(float(r_v), 4)
            f1 = round(float(f), 4)
        except Exception:
            precision = recall = f1 = round(acc, 4)
        output[c] = {
            "total": total, "correct": correct, "accuracy": round(acc, 4),
            "precision": precision, "recall": recall, "f1": f1,
        }
    return output


def compute_technique_metrics(results):
    """V2 specific: accuracy per adversarial technique."""
    tech = defaultdict(lambda: {"total": 0, "correct": 0})
    for r in results:
        t = r.get("adversarial_technique", "unknown")
        tech[t]["total"] += 1
        if r["correct"]:
            tech[t]["correct"] += 1
    output = {}
    for t in sorted(tech):
        total = tech[t]["total"]
        correct = tech[t]["correct"]
        output[t] = {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else 0.0,
        }
    return output


def compute_decision_transitions(results):
    transitions = defaultdict(int)
    for r in results:
        if not r["correct"]:
            key = f"{r['expected_decision']} → {r['predicted_decision']}"
            transitions[key] += 1
    return dict(sorted(transitions.items()))


def evaluate_case(case):
    intent = case["ground_truth_intent"]
    sql = case["generated_sql"]
    user_request = case["user_request"]
    expected = case["expected_decision"]

    start = time.perf_counter()
    result = guardian_check(user_request, sql, known_intent=intent)
    elapsed_ms = (time.perf_counter() - start) * 1000

    predicted = result["risk"]["decision"]
    correct = predicted == expected

    return {
        "case_id": case["case_id"],
        "category": case.get("category", "UNKNOWN"),
        "adversarial_technique": case.get("adversarial_technique", "unknown"),
        "difficulty": case.get("difficulty", "unknown"),
        "schema": case.get("schema", "unknown"),
        "user_request": user_request,
        "SQL": sql,
        "expected_decision": expected,
        "predicted_decision": predicted,
        "correct": correct,
        "latency_ms": round(elapsed_ms, 4),
        "risk_score": result["risk"].get("risk_score"),
        "risk_level": result["risk"].get("risk_level"),
        "scope": result.get("scope"),
        "impact": result.get("impact", {}).get("impact_type"),
        "mismatches": result.get("intent_sql", {}).get("mismatches", []),
    }


def build_failure_analysis(results):
    failures = []
    for r in results:
        if not r["correct"]:
            failures.append({
                "case_id": r["case_id"],
                "intent": r["user_request"],
                "SQL": r["SQL"],
                "expected_decision": r["expected_decision"],
                "predicted_decision": r["predicted_decision"],
                "risk_score": r.get("risk_score"),
                "scope": r.get("scope"),
                "impact": r.get("impact"),
                "mismatch_type": r.get("mismatches", []),
                "category": r.get("category"),
                "adversarial_technique": r.get("adversarial_technique"),
                "failure_type": (
                    f"{r['expected_decision']}_predicted_as_"
                    f"{r['predicted_decision']}"
                ),
            })
    return failures


def main():
    print()
    print("=" * 70)
    print("GUARDIANAGENT LARGE-SCALE V2 ADVERSARIAL EVALUATION (1500 cases)")
    print("=" * 70)

    dataset = load_dataset()
    print(f"\nLoaded {len(dataset)} cases from: {DATASET_PATH}")
    print("Intent mode      : GROUND-TRUTH (no Gemini API calls)")
    print("SQL execution    : DISABLED")

    results = []
    errors = []

    for idx, case in enumerate(dataset, start=1):
        try:
            r = evaluate_case(case)
            results.append(r)
        except Exception as exc:
            errors.append({
                "case_id": case.get("case_id", f"CASE_{idx}"),
                "error": str(exc),
            })
        if idx % 100 == 0 or idx == len(dataset):
            correct = sum(r["correct"] for r in results)
            print(f"  Progress: {idx}/{len(dataset)} | "
                  f"Correct: {correct} | Errors: {len(errors)}")

    y_true = [r["expected_decision"] for r in results]
    y_pred = [r["predicted_decision"] for r in results]

    metrics = compute_metrics(y_true, y_pred)
    ci = compute_confidence_interval(metrics["accuracy"], len(results))
    safety = compute_safety_metrics(y_true, y_pred)
    latency = compute_latency_stats([r["latency_ms"] for r in results])
    category = compute_category_metrics(results)
    technique = compute_technique_metrics(results)
    transitions = compute_decision_transitions(results)
    failures = build_failure_analysis(results)

    summary = {
        "dataset": {
            "name": "V2 Large Adversarial (1500 cases)",
            "file": str(DATASET_PATH),
            "total_cases": len(dataset),
            "evaluated": len(results),
            "errors": len(errors),
        },
        "evaluation": {
            "intent_mode": "GROUND-TRUTH",
            "gemini_api_calls": 0,
            "sql_execution": False,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        },
        "metrics": metrics,
        "confidence_interval_95": ci,
        "safety_metrics": safety,
        "latency_ms": latency,
        "category_wise": category,
        "adversarial_technique_wise": technique,
        "decision_transitions": transitions,
        "failure_count": len(failures),
        "failure_analysis": failures,
        "run_errors": errors,
        "all_results": results,
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Print results
    print()
    print("=" * 70)
    print("V2 RESULTS")
    print("=" * 70)
    print(f"\nTotal cases   : {len(dataset)}")
    print(f"Evaluated     : {len(results)}")
    print(f"Correct       : {sum(r['correct'] for r in results)}")
    print(f"Incorrect     : {len(failures)}")
    print(f"Errors        : {len(errors)}")
    print()
    print(f"Accuracy      : {metrics['accuracy_pct']:.2f}%  "
          f"(95% CI: [{ci['lower']:.4f}, {ci['upper']:.4f}])")
    print(f"Macro Prec    : {metrics['macro_precision']:.4f}")
    print(f"Macro Recall  : {metrics['macro_recall']:.4f}")
    print(f"Macro F1      : {metrics['macro_f1']:.4f}")

    print()
    print(f"{'Decision':<12} {'Precision':>10} {'Recall':>10} "
          f"{'F1':>10} {'Support':>10}")
    print("-" * 55)
    for label in DECISIONS:
        pc = metrics["per_class"][label]
        print(f"{label:<12} {pc['precision']:>10.4f} {pc['recall']:>10.4f} "
              f"{pc['f1']:>10.4f} {pc['support']:>10}")

    print()
    print("Confusion Matrix:")
    m = metrics["confusion_matrix"]["matrix"]
    print(f"{'':16} {'ALLOW':>10} {'CONFIRM':>10} {'BLOCK':>10}")
    for i, label in enumerate(DECISIONS):
        print(f"Actual {label:<10} {m[i][0]:>10} {m[i][1]:>10} {m[i][2]:>10}")

    print()
    print("Safety Metrics:")
    print(f"  Unsafe miss rate    : {safety['unsafe_miss_rate']:.4f}  "
          f"({safety['unsafe_miss_count']}/{safety['total_dangerous_cases']})")
    print(f"  Unsafe ALLOWED      : {safety['unsafe_allowed_count']}")
    print(f"  Unsafe CONFIRMED    : {safety['unsafe_confirmed_count']}")
    print(f"  Safe false-block    : {safety['safe_false_block_rate']:.4f}  "
          f"({safety['safe_false_block_count']}/{safety['total_safe_cases']})")
    print(f"  Safe false-confirm  : {safety['safe_false_confirm_count']}")

    print()
    print("Latency:")
    for k in ["mean_ms", "median_ms", "std_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]:
        print(f"  {k:<12}: {latency[k]:.4f} ms")

    print()
    print("Adversarial Technique Accuracy (worst 10):")
    for tech, stats in sorted(
        technique.items(), key=lambda x: x[1]["accuracy"]
    )[:10]:
        print(f"  {tech:<40} {stats['correct']}/{stats['total']} "
              f"({stats['accuracy']:.2%})")

    # Update combined
    combined = {}
    if COMBINED_PATH.exists():
        with open(COMBINED_PATH, "r", encoding="utf-8") as f:
            combined = json.load(f)

    combined["v2_1500"] = {
        "accuracy": metrics["accuracy_pct"],
        "macro_f1": metrics["macro_f1"],
        "unsafe_miss_rate": safety["unsafe_miss_rate"],
        "safe_false_block_rate": safety["safe_false_block_rate"],
        "total_cases": len(results),
        "confidence_interval_95": ci,
        "per_class": metrics["per_class"],
        "safety_metrics": safety,
        "latency_ms": latency,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(COMBINED_PATH, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to: {RESULTS_PATH}")

    print()
    print("=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"V2:")
    print(f"  {len(results)} cases")
    print(f"  Accuracy : {metrics['accuracy_pct']:.2f}%")
    print(f"  Macro-F1 : {metrics['macro_f1']:.4f}")
    print(f"  Unsafe Miss: {safety['unsafe_miss_rate']:.4f}")
    print(f"  False-Block: {safety['safe_false_block_rate']:.4f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
