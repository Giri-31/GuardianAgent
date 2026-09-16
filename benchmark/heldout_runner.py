import sys
import json
import time
from pathlib import Path
from collections import defaultdict

from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix
)


# ============================================================
# PROJECT PATH
# ============================================================

# Project root:
# D:\Git\GuardianAgent

ROOT = Path(__file__).resolve().parent.parent

# Allow Python to import guardian.py from the project root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# GUARDIANAGENT IMPORT
# ============================================================

from guardian import guardian_check


# ============================================================
# FILE PATHS
# ============================================================

DATASET_PATH = (
    ROOT
    / "benchmark"
    / "heldout_dataset.json"
)

RESULTS_PATH = (
    ROOT
    / "benchmark"
    / "heldout_results.json"
)


# ============================================================
# LOAD DATASET
# ============================================================

def load_dataset():

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found:\n{DATASET_PATH}"
        )

    with open(
        DATASET_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


# ============================================================
# EVALUATE ONE CASE
# ============================================================

def evaluate_case(case):

    user_request = case["user_request"]

    generated_sql = case["generated_sql"]

    ground_truth_intent = (
        case["ground_truth_intent"]
    )

    expected_decision = (
        case["expected_decision"]
    )

    # Start latency measurement
    start_time = time.perf_counter()

    # IMPORTANT:
    # Use ground-truth intent so Gemini is NOT called.
    #
    # SQL is analyzed only.
    # SQL is NEVER executed.
    result = guardian_check(
        user_request,
        generated_sql,
        known_intent=ground_truth_intent
    )

    end_time = time.perf_counter()

    latency_ms = (
        end_time - start_time
    ) * 1000

    # Extract GuardianAgent decision
    predicted_decision = (
        result["risk"]["decision"]
    )

    correct = (
        predicted_decision
        == expected_decision
    )

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "user_request": user_request,
        "generated_sql": generated_sql,

        "expected_decision":
            expected_decision,

        "predicted_decision":
            predicted_decision,

        "correct":
            correct,

        "latency_ms":
            round(latency_ms, 4),

        "risk_score":
            result["risk"].get(
                "risk_score"
            ),

        "risk_level":
            result["risk"].get(
                "risk_level"
            ),

        "mismatches":
            result["intent_sql"].get(
                "mismatches",
                []
            )
    }


# ============================================================
# MAIN BENCHMARK
# ============================================================

def main():

    cases = load_dataset()

    print()
    print("=" * 70)
    print(
        "GUARDIANAGENT "
        "INDEPENDENT HELD-OUT BENCHMARK"
    )
    print("=" * 70)

    print()
    print(
        f"Loaded {len(cases)} held-out cases."
    )

    print()
    print(
        "Intent mode      : GROUND-TRUTH"
    )

    print(
        "Gemini API calls : 0"
    )

    print(
        "SQL execution    : DISABLED"
    )

    print()

    results = []

    errors = []

    # ========================================================
    # RUN CASES
    # ========================================================

    for index, case in enumerate(
        cases,
        start=1
    ):

        try:

            result = evaluate_case(
                case
            )

            results.append(result)

        except Exception as error:

            errors.append({
                "case_id":
                    case.get(
                        "case_id",
                        f"CASE_{index}"
                    ),

                "error":
                    str(error)
            })

        # Progress output
        if (
            index % 25 == 0
            or index == len(cases)
        ):

            correct_count = sum(
                result["correct"]
                for result in results
            )

            print(
                f"Progress: "
                f"{index}/{len(cases)} "
                f"| Correct: "
                f"{correct_count} "
                f"| Errors: "
                f"{len(errors)}"
            )

    # ========================================================
    # METRICS
    # ========================================================

    y_true = [
        result["expected_decision"]
        for result in results
    ]

    y_pred = [
        result["predicted_decision"]
        for result in results
    ]

    labels = [
        "ALLOW",
        "CONFIRM",
        "BLOCK"
    ]

    # --------------------------------------------------------
    # Accuracy
    # --------------------------------------------------------

    accuracy = accuracy_score(
        y_true,
        y_pred
    )

    # --------------------------------------------------------
    # Precision / Recall / F1
    # --------------------------------------------------------

    (
        precision,
        recall,
        f1,
        support
    ) = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=labels,
        zero_division=0
    )

    macro_precision = (
        precision.mean()
    )

    macro_recall = (
        recall.mean()
    )

    macro_f1 = (
        f1.mean()
    )

    # --------------------------------------------------------
    # Confusion matrix
    # --------------------------------------------------------

    confusion_matrix_values = (
        confusion_matrix(
            y_true,
            y_pred,
            labels=labels
        )
    )

    confusion = {}

    for i, actual in enumerate(labels):

        confusion[actual] = {}

        for j, predicted in enumerate(labels):

            confusion[actual][predicted] = (
                int(
                    confusion_matrix_values[i][j]
                )
            )

    # ========================================================
    # CATEGORY-WISE RESULTS
    # ========================================================

    category_stats = defaultdict(
        lambda: {
            "total": 0,
            "correct": 0
        }
    )

    for result in results:

        category = result["category"]

        category_stats[
            category
        ]["total"] += 1

        if result["correct"]:

            category_stats[
                category
            ]["correct"] += 1

    category_results = {}

    for category in sorted(
        category_stats.keys()
    ):

        total = category_stats[
            category
        ]["total"]

        correct = category_stats[
            category
        ]["correct"]

        category_results[category] = {
            "total":
                total,

            "correct":
                correct,

            "accuracy":
                round(
                    correct / total,
                    4
                )
        }

    # ========================================================
    # LATENCY
    # ========================================================

    latencies = [
        result["latency_ms"]
        for result in results
    ]

    if latencies:

        sorted_latencies = sorted(
            latencies
        )

        mean_latency = (
            sum(latencies)
            / len(latencies)
        )

        n = len(sorted_latencies)

        if n % 2 == 0:

            median_latency = (
                sorted_latencies[
                    n // 2 - 1
                ]
                +
                sorted_latencies[
                    n // 2
                ]
            ) / 2

        else:

            median_latency = (
                sorted_latencies[
                    n // 2
                ]
            )

        minimum_latency = min(
            latencies
        )

        maximum_latency = max(
            latencies
        )

    else:

        mean_latency = 0
        median_latency = 0
        minimum_latency = 0
        maximum_latency = 0

    # ========================================================
    # COUNTS
    # ========================================================

    correct_total = sum(
        result["correct"]
        for result in results
    )

    incorrect_total = (
        len(results)
        - correct_total
    )

    # ========================================================
    # BUILD SUMMARY
    # ========================================================

    summary = {

        "dataset": {

            "name":
                "Independent Held-Out Benchmark",

            "cases":
                len(cases),

            "evaluated":
                len(results),

            "errors":
                len(errors)
        },

        "evaluation": {

            "intent_mode":
                "GROUND-TRUTH",

            "gemini_api_calls":
                0,

            "sql_execution":
                False
        },

        "metrics": {

            "accuracy":
                round(
                    accuracy,
                    4
                ),

            "macro_precision":
                round(
                    macro_precision,
                    4
                ),

            "macro_recall":
                round(
                    macro_recall,
                    4
                ),

            "macro_f1":
                round(
                    macro_f1,
                    4
                )
        },

        "counts": {

            "correct":
                correct_total,

            "incorrect":
                incorrect_total,

            "errors":
                len(errors)
        },

        "confusion_matrix":
            confusion,

        "per_class":
            {},

        "category_wise":
            category_results,

        "latency_ms": {

            "mean":
                round(
                    mean_latency,
                    4
                ),

            "median":
                round(
                    median_latency,
                    4
                ),

            "minimum":
                round(
                    minimum_latency,
                    4
                ),

            "maximum":
                round(
                    maximum_latency,
                    4
                )
        },

        "errors":
            errors,

        "results":
            results
    }

    # ========================================================
    # PER-CLASS METRICS
    # ========================================================

    for i, label in enumerate(labels):

        summary[
            "per_class"
        ][label] = {

            "precision":
                round(
                    precision[i],
                    4
                ),

            "recall":
                round(
                    recall[i],
                    4
                ),

            "f1":
                round(
                    f1[i],
                    4
                ),

            "support":
                int(
                    support[i]
                )
        }

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    print()

    print(
        f"Total cases : "
        f"{len(cases)}"
    )

    print(
        f"Correct     : "
        f"{correct_total}"
    )

    print(
        f"Incorrect   : "
        f"{incorrect_total}"
    )

    print(
        f"Errors      : "
        f"{len(errors)}"
    )

    print(
        f"Accuracy    : "
        f"{accuracy:.2%}"
    )

    print(
        f"Macro F1    : "
        f"{macro_f1:.4f}"
    )

    # ========================================================
    # PER-CLASS RESULTS
    # ========================================================

    print()
    print(
        "Decision       Precision      "
        "Recall          F1"
    )

    for i, label in enumerate(labels):

        print(
            f"{label:<14}"
            f"{precision[i]:>10.4f}"
            f"{recall[i]:>15.4f}"
            f"{f1[i]:>15.4f}"
        )

    # ========================================================
    # CONFUSION MATRIX
    # ========================================================

    print()
    print("Confusion Matrix")
    print()

    print(
        f"{'Actual / Pred':<16}"
        f"{'ALLOW':>10}"
        f"{'CONFIRM':>10}"
        f"{'BLOCK':>10}"
    )

    for actual in labels:

        print(
            f"{actual:<16}"
            f"{confusion[actual]['ALLOW']:>10}"
            f"{confusion[actual]['CONFIRM']:>10}"
            f"{confusion[actual]['BLOCK']:>10}"
        )

    # ========================================================
    # CATEGORY-WISE RESULTS
    # ========================================================

    print()
    print("Category-wise:")

    for category, stats in (
        category_results.items()
    ):

        print(
            f"{category:<25}"
            f"{stats['correct']}/"
            f"{stats['total']} "
            f"({stats['accuracy']:.2%})"
        )

    # ========================================================
    # LATENCY
    # ========================================================

    print()
    print("Latency:")

    print(
        f"Mean     "
        f"{mean_latency:.4f} ms"
    )

    print(
        f"Median   "
        f"{median_latency:.4f} ms"
    )

    print(
        f"Minimum  "
        f"{minimum_latency:.4f} ms"
    )

    print(
        f"Maximum  "
        f"{maximum_latency:.4f} ms"
    )

    # ========================================================
    # SAVE RESULTS
    # ========================================================

    with open(
        RESULTS_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            summary,
            file,
            indent=2
        )

    print()
    print(
        f"Results saved to:"
    )

    print(
        RESULTS_PATH
    )

    print("=" * 70)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()