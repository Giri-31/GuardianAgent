import json
import sys
import time
import sqlite3
from pathlib import Path
from collections import defaultdict


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

DATASET_FILE = BASE_DIR / "generated_dataset.json"
RESULTS_FILE = BASE_DIR / "benchmark_results.json"

sys.path.insert(0, str(PROJECT_DIR))

from guardian import guardian_check


# ============================================================
# VALID DECISIONS
# ============================================================

VALID_DECISIONS = {
    "ALLOW",
    "CONFIRM",
    "BLOCK"
}


# ============================================================
# LOAD DATASET
# ============================================================

def load_dataset():

    with open(
        DATASET_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# ============================================================
# DATABASE SNAPSHOT
# ============================================================

def database_snapshot():

    db_file = PROJECT_DIR / "company.db"

    connection = sqlite3.connect(db_file)
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, name, department, status, salary
        FROM employees
        ORDER BY id
    """)

    rows = cursor.fetchall()

    connection.close()

    return rows


# ============================================================
# CONFUSION MATRIX
# ============================================================

def build_confusion_matrix(results):

    labels = [
        "ALLOW",
        "CONFIRM",
        "BLOCK"
    ]

    matrix = {
        actual: {
            predicted: 0
            for predicted in labels
        }
        for actual in labels
    }

    for result in results:

        actual = result["expected_decision"]
        predicted = result["predicted_decision"]

        if (
            actual in labels
            and predicted in labels
        ):

            matrix[actual][predicted] += 1

    return matrix


# ============================================================
# OVERALL METRICS
# ============================================================

def calculate_metrics(results):

    labels = [
        "ALLOW",
        "CONFIRM",
        "BLOCK"
    ]

    total = len(results)

    correct = sum(
        1
        for result in results
        if result["expected_decision"]
        == result["predicted_decision"]
    )

    accuracy = (
        correct / total
        if total > 0
        else 0.0
    )

    metrics = {}

    for label in labels:

        true_positive = sum(
            1
            for result in results
            if (
                result["expected_decision"] == label
                and
                result["predicted_decision"] == label
            )
        )

        false_positive = sum(
            1
            for result in results
            if (
                result["expected_decision"] != label
                and
                result["predicted_decision"] == label
            )
        )

        false_negative = sum(
            1
            for result in results
            if (
                result["expected_decision"] == label
                and
                result["predicted_decision"] != label
            )
        )

        precision = (
            true_positive /
            (true_positive + false_positive)
            if true_positive + false_positive > 0
            else 0.0
        )

        recall = (
            true_positive /
            (true_positive + false_negative)
            if true_positive + false_negative > 0
            else 0.0
        )

        f1 = (
            2 * precision * recall /
            (precision + recall)
            if precision + recall > 0
            else 0.0
        )

        metrics[label] = {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1
        }

    macro_f1 = sum(
        metrics[label]["f1"]
        for label in labels
    ) / len(labels)

    return {
        "total_cases": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_decision": metrics
    }


# ============================================================
# CATEGORY METRICS
# ============================================================

def calculate_category_metrics(results):

    categories = defaultdict(list)

    for result in results:

        categories[
            result["category"]
        ].append(result)

    output = {}

    for category, category_results in sorted(
        categories.items()
    ):

        total = len(category_results)

        correct = sum(
            1
            for result in category_results
            if (
                result["expected_decision"]
                ==
                result["predicted_decision"]
            )
        )

        accuracy = (
            correct / total
            if total > 0
            else 0.0
        )

        output[category] = {
            "total": total,
            "correct": correct,
            "incorrect": total - correct,
            "accuracy": accuracy
        }

    return output


# ============================================================
# LATENCY
# ============================================================

def calculate_latency(results):

    latencies = [
        result["latency_ms"]
        for result in results
        if result["error"] is None
    ]

    if not latencies:

        return {
            "count": 0,
            "mean_ms": None,
            "median_ms": None,
            "min_ms": None,
            "max_ms": None
        }

    latencies = sorted(latencies)

    count = len(latencies)

    mean_ms = sum(latencies) / count

    middle = count // 2

    if count % 2 == 0:

        median_ms = (
            latencies[middle - 1]
            + latencies[middle]
        ) / 2

    else:

        median_ms = latencies[middle]

    return {
        "count": count,
        "mean_ms": mean_ms,
        "median_ms": median_ms,
        "min_ms": min(latencies),
        "max_ms": max(latencies)
    }


# ============================================================
# RUN ONE CASE
# ============================================================

def run_case(case):

    user_intent = case["user_intent"]
    generated_sql = case["generated_sql"]

    ground_truth_intent = case[
        "ground_truth_intent"
    ]

    start_time = time.perf_counter()

    try:

        # IMPORTANT:
        # Use the benchmark's ground-truth intent.
        #
        # This prevents Gemini API calls during the
        # safety benchmark.

        guardian_result = guardian_check(
            user_intent,
            generated_sql,
            known_intent=ground_truth_intent
        )

        elapsed = (
            time.perf_counter()
            - start_time
        )

        risk = guardian_result.get(
            "risk",
            {}
        )

        predicted_decision = risk.get(
            "decision",
            "UNKNOWN"
        )

        risk_score = risk.get(
            "risk_score"
        )

        risk_level = risk.get(
            "risk_level"
        )

        if predicted_decision not in VALID_DECISIONS:

            predicted_decision = "UNKNOWN"

        return {

            "id": case["id"],

            "user_intent": user_intent,

            "ground_truth_intent":
                ground_truth_intent,

            "generated_sql":
                generated_sql,

            "category":
                case["category"],

            "expected_decision":
                case["expected_decision"],

            "predicted_decision":
                predicted_decision,

            "risk_score":
                risk_score,

            "risk_level":
                risk_level,

            "guardian_scope":
                guardian_result.get("scope"),

            "impact":
                guardian_result.get("impact"),

            "intent_sql":
                guardian_result.get("intent_sql"),

            "latency_ms":
                elapsed * 1000,

            "correct":
                predicted_decision
                == case["expected_decision"],

            "error":
                None
        }

    except Exception as e:

        elapsed = (
            time.perf_counter()
            - start_time
        )

        return {

            "id": case["id"],

            "user_intent": user_intent,

            "ground_truth_intent":
                ground_truth_intent,

            "generated_sql":
                generated_sql,

            "category":
                case["category"],

            "expected_decision":
                case["expected_decision"],

            "predicted_decision":
                "ERROR",

            "risk_score":
                None,

            "risk_level":
                None,

            "guardian_scope":
                None,

            "impact":
                None,

            "intent_sql":
                None,

            "latency_ms":
                elapsed * 1000,

            "correct":
                False,

            "error":
                str(e)
        }


# ============================================================
# PRINT CONFUSION MATRIX
# ============================================================

def print_confusion_matrix(matrix):

    print()
    print("=" * 70)
    print("CONFUSION MATRIX")
    print("=" * 70)
    print()

    print(
        f"{'Actual / Predicted':20s}"
        f"{'ALLOW':>10s}"
        f"{'CONFIRM':>10s}"
        f"{'BLOCK':>10s}"
    )

    print("-" * 50)

    for actual in [
        "ALLOW",
        "CONFIRM",
        "BLOCK"
    ]:

        print(
            f"{actual:20s}"
            f"{matrix[actual]['ALLOW']:10d}"
            f"{matrix[actual]['CONFIRM']:10d}"
            f"{matrix[actual]['BLOCK']:10d}"
        )


# ============================================================
# PRINT OVERALL METRICS
# ============================================================

def print_metrics(metrics):

    print()
    print("=" * 70)
    print("OVERALL METRICS")
    print("=" * 70)
    print()

    print(
        f"Total cases : "
        f"{metrics['total_cases']}"
    )

    print(
        f"Correct     : "
        f"{metrics['correct']}"
    )

    print(
        f"Incorrect   : "
        f"{metrics['incorrect']}"
    )

    print(
        f"Accuracy    : "
        f"{metrics['accuracy'] * 100:.2f}%"
    )

    print(
        f"Macro F1    : "
        f"{metrics['macro_f1']:.4f}"
    )

    print()

    print(
        f"{'Decision':12s}"
        f"{'Precision':>12s}"
        f"{'Recall':>12s}"
        f"{'F1':>12s}"
    )

    print("-" * 48)

    for label in [
        "ALLOW",
        "CONFIRM",
        "BLOCK"
    ]:

        values = metrics[
            "per_decision"
        ][label]

        print(
            f"{label:12s}"
            f"{values['precision']:12.4f}"
            f"{values['recall']:12.4f}"
            f"{values['f1']:12.4f}"
        )


# ============================================================
# PRINT CATEGORY METRICS
# ============================================================

def print_category_metrics(
    category_metrics
):

    print()
    print("=" * 70)
    print("CATEGORY-WISE RESULTS")
    print("=" * 70)
    print()

    print(
        f"{'Category':25s}"
        f"{'Total':>8s}"
        f"{'Correct':>10s}"
        f"{'Accuracy':>12s}"
    )

    print("-" * 60)

    for category, values in (
        category_metrics.items()
    ):

        print(
            f"{category:25s}"
            f"{values['total']:8d}"
            f"{values['correct']:10d}"
            f"{values['accuracy'] * 100:11.2f}%"
        )


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(
    results,
    metrics,
    category_metrics,
    confusion_matrix,
    latency
):

    output = {

        "benchmark": {

            "dataset":
                str(DATASET_FILE),

            "case_count":
                len(results),

            "guardian":
                "GuardianAgent",

            "database":
                str(PROJECT_DIR / "company.db"),

            "intent_mode":
                "ground_truth_intent",

            "gemini_calls":
                0
        },

        "metrics":
            metrics,

        "category_metrics":
            category_metrics,

        "confusion_matrix":
            confusion_matrix,

        "latency":
            latency,

        "results":
            results
    }

    with open(
        RESULTS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("GUARDIANAGENT RESEARCH BENCHMARK RUNNER")
    print("=" * 70)

    print()
    print(
        f"Dataset : {DATASET_FILE}"
    )

    print(
        f"Results : {RESULTS_FILE}"
    )

    print()
    print(
        "Intent mode : "
        "GROUND-TRUTH"
    )

    print(
        "Gemini API calls : 0"
    )

    # --------------------------------------------------------
    # Load dataset
    # --------------------------------------------------------

    dataset = load_dataset()

    print()
    print(
        f"Loaded {len(dataset)} "
        f"benchmark cases."
    )

    # --------------------------------------------------------
    # Database snapshot
    # --------------------------------------------------------

    before_snapshot = (
        database_snapshot()
    )

    # --------------------------------------------------------
    # Run benchmark
    # --------------------------------------------------------

    results = []

    print()
    print("=" * 70)
    print("RUNNING BENCHMARK")
    print("=" * 70)

    for index, case in enumerate(
        dataset,
        start=1
    ):

        result = run_case(case)

        results.append(result)

        if (
            index % 25 == 0
            or index == len(dataset)
        ):

            correct_so_far = sum(
                1
                for r in results
                if r["correct"]
            )

            errors_so_far = sum(
                1
                for r in results
                if r["error"] is not None
            )

            print(
                f"Progress: "
                f"{index}/{len(dataset)}"
                f" | Correct: "
                f"{correct_so_far}"
                f" | Errors: "
                f"{errors_so_far}"
            )

    # --------------------------------------------------------
    # Database integrity
    # --------------------------------------------------------

    after_snapshot = (
        database_snapshot()
    )

    if before_snapshot != after_snapshot:

        print()
        print(
            "WARNING: Database contents "
            "changed during benchmark execution."
        )

    else:

        print()
        print(
            "Database integrity check: PASSED"
        )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    metrics = calculate_metrics(
        results
    )

    category_metrics = (
        calculate_category_metrics(
            results
        )
    )

    confusion_matrix = (
        build_confusion_matrix(
            results
        )
    )

    latency = calculate_latency(
        results
    )

    # --------------------------------------------------------
    # Print results
    # --------------------------------------------------------

    print_metrics(metrics)

    print_confusion_matrix(
        confusion_matrix
    )

    print_category_metrics(
        category_metrics
    )

    # --------------------------------------------------------
    # Latency
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("LATENCY")
    print("=" * 70)

    if latency["count"] > 0:

        print(
            f"Mean latency   : "
            f"{latency['mean_ms']:.3f} ms"
        )

        print(
            f"Median latency : "
            f"{latency['median_ms']:.3f} ms"
        )

        print(
            f"Minimum        : "
            f"{latency['min_ms']:.3f} ms"
        )

        print(
            f"Maximum        : "
            f"{latency['max_ms']:.3f} ms"
        )

    else:

        print(
            "No successful benchmark cases."
        )

    # --------------------------------------------------------
    # Errors
    # --------------------------------------------------------

    errors = [
        result
        for result in results
        if result["error"] is not None
    ]

    print()
    print(
        f"Execution errors: "
        f"{len(errors)}"
    )

    if errors:

        print()
        print("FIRST ERRORS")
        print("-" * 50)

        for result in errors[:10]:

            print(
                result["id"],
                ":",
                result["error"]
            )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_results(
        results,
        metrics,
        category_metrics,
        confusion_matrix,
        latency
    )

    print()
    print("=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)

    print()
    print("Results saved to:")

    print(RESULTS_FILE)


if __name__ == "__main__":

    main()