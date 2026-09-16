import sys
import json
import time
import sqlite3
from pathlib import Path
from collections import defaultdict

from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix
)


# ============================================================
# PATH SETUP
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# GUARDIANAGENT IMPORT
# ============================================================

from guardian import guardian_check


# ============================================================
# PATHS
# ============================================================

DATASET_PATH = (
    ROOT
    / "benchmark"
    / "heldout_v2_dataset.json"
)

RESULTS_PATH = (
    ROOT
    / "benchmark"
    / "heldout_v2_results.json"
)

DB_PATH = ROOT / "company.db"


# ============================================================
# DECISION LABELS
# ============================================================

DECISIONS = [
    "ALLOW",
    "CONFIRM",
    "BLOCK"
]


# ============================================================
# LOAD DATASET
# ============================================================

with open(
    DATASET_PATH,
    "r",
    encoding="utf-8"
) as file:

    dataset = json.load(file)


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(
    expected,
    predicted
):

    accuracy = accuracy_score(
        expected,
        predicted
    )

    precision, recall, f1, support = (
        precision_recall_fscore_support(
            expected,
            predicted,
            labels=DECISIONS,
            zero_division=0
        )
    )

    matrix = confusion_matrix(
        expected,
        predicted,
        labels=DECISIONS
    )

    per_class = {}

    for i, decision in enumerate(
        DECISIONS
    ):

        per_class[decision] = {

            "precision": round(
                float(precision[i]),
                4
            ),

            "recall": round(
                float(recall[i]),
                4
            ),

            "f1": round(
                float(f1[i]),
                4
            ),

            "support": int(
                support[i]
            )
        }


    macro_f1 = sum(f1) / len(f1)


    return {

        "accuracy": round(
            float(accuracy) * 100,
            2
        ),

        "macro_f1": round(
            float(macro_f1),
            4
        ),

        "per_class": per_class,

        "confusion_matrix": {

            "labels": DECISIONS,

            "matrix": matrix.tolist()
        }
    }


# ============================================================
# CATEGORY-WISE METRICS
# ============================================================

def calculate_category_metrics(
    expected,
    predicted,
    categories
):

    results = defaultdict(
        lambda: {
            "total": 0,
            "correct": 0
        }
    )


    for category, actual, prediction in zip(
        categories,
        expected,
        predicted
    ):

        results[category]["total"] += 1

        if actual == prediction:

            results[category]["correct"] += 1


    output = {}


    for category, values in sorted(
        results.items()
    ):

        output[category] = {

            "correct":
                values["correct"],

            "total":
                values["total"],

            "accuracy": round(
                (
                    values["correct"]
                    / values["total"]
                ) * 100,
                2
            )
        }


    return output


# ============================================================
# SAFETY METRICS
# ============================================================

def calculate_safety_metrics(
    expected,
    predicted
):

    dangerous_not_blocked = 0

    safe_incorrectly_blocked = 0


    for actual, prediction in zip(
        expected,
        predicted
    ):

        # Expected BLOCK but received
        # ALLOW or CONFIRM.
        if (
            actual == "BLOCK"
            and prediction != "BLOCK"
        ):

            dangerous_not_blocked += 1


        # Expected ALLOW but received BLOCK.
        if (
            actual == "ALLOW"
            and prediction == "BLOCK"
        ):

            safe_incorrectly_blocked += 1


    return {

        "dangerous_not_blocked":
            dangerous_not_blocked,

        "safe_incorrectly_blocked":
            safe_incorrectly_blocked
    }


# ============================================================
# DATABASE INTEGRITY SNAPSHOT
# ============================================================

def database_snapshot():

    conn = sqlite3.connect(
        DB_PATH
    )

    cursor = conn.cursor()


    cursor.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' "
        "ORDER BY name"
    )

    tables = [
        row[0]
        for row in cursor.fetchall()
    ]


    table_data = {}


    for table in tables:

        # Table names come from sqlite_master,
        # not user input.
        cursor.execute(
            f"SELECT COUNT(*) FROM [{table}]"
        )

        table_data[table] = (
            cursor.fetchone()[0]
        )


    conn.close()


    return {

        "tables": tables,

        "row_counts": table_data
    }


# ============================================================
# RUN BENCHMARK
# ============================================================

def run_benchmark():

    expected = []

    predicted = []

    categories = []

    latencies = []

    failures = []


    # --------------------------------------------------------
    # DATABASE SNAPSHOT BEFORE
    # --------------------------------------------------------

    before_snapshot = (
        database_snapshot()
    )


    # ========================================================
    # PROCESS CASES
    # ========================================================

    for test in dataset:

        case_id = test["case_id"]

        request = test["user_request"]

        sql = test["generated_sql"]

        ground_truth_intent = (
            test["ground_truth_intent"]
        )

        expected_decision = (
            test["expected_decision"]
        )

        category = test["category"]


        expected.append(
            expected_decision
        )

        categories.append(
            category
        )


        # ----------------------------------------------------
        # START TIMER
        # ----------------------------------------------------

        start = time.perf_counter()


        # ----------------------------------------------------
        # RUN GUARDIANAGENT
        #
        # Ground-truth intent is supplied so that this
        # benchmark measures GuardianAgent's safety logic
        # without consuming Gemini API requests.
        #
        # SQL is analyzed but NEVER executed.
        # ----------------------------------------------------

        result = guardian_check(
            request,
            sql,
            known_intent=ground_truth_intent
        )


        # ----------------------------------------------------
        # END TIMER
        # ----------------------------------------------------

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000


        latencies.append(
            elapsed_ms
        )


        # ----------------------------------------------------
        # DECISION
        # ----------------------------------------------------

        prediction = (
            result["risk"]["decision"]
        )


        predicted.append(
            prediction
        )


        # ----------------------------------------------------
        # RECORD FAILURES
        # ----------------------------------------------------

        if prediction != expected_decision:

            failures.append({

                "case_id":
                    case_id,

                "category":
                    category,

                "user_request":
                    request,

                "generated_sql":
                    sql,

                "expected":
                    expected_decision,

                "predicted":
                    prediction,

                "risk_score":
                    result["risk"].get(
                        "risk_score"
                    ),

                "risk_level":
                    result["risk"].get(
                        "risk_level"
                    ),

                "risk_components":
                    result["risk"].get(
                        "risk_components"
                    ),

                "intent_sql":
                    result.get(
                        "intent_sql"
                    ),

                "scope":
                    result.get(
                        "scope"
                    ),

                "impact":
                    result.get(
                        "impact"
                    )
            })


    # ========================================================
    # DATABASE SNAPSHOT AFTER
    # ========================================================

    after_snapshot = (
        database_snapshot()
    )


    database_integrity = (
        before_snapshot
        == after_snapshot
    )


    # ========================================================
    # METRICS
    # ========================================================

    metrics = calculate_metrics(
        expected,
        predicted
    )


    metrics["category_results"] = (
        calculate_category_metrics(
            expected,
            predicted,
            categories
        )
    )


    metrics["safety"] = (
        calculate_safety_metrics(
            expected,
            predicted
        )
    )


    # ========================================================
    # LATENCY
    # ========================================================

    sorted_latencies = sorted(
        latencies
    )


    median_latency = (
        sorted_latencies[
            len(sorted_latencies) // 2
        ]
    )


    metrics["latency_ms"] = {

        "mean": round(
            sum(latencies)
            / len(latencies),
            4
        ),

        "median": round(
            median_latency,
            4
        ),

        "minimum": round(
            min(latencies),
            4
        ),

        "maximum": round(
            max(latencies),
            4
        )
    }


    # ========================================================
    # EXTRA INFORMATION
    # ========================================================

    metrics["total_cases"] = (
        len(dataset)
    )

    metrics["correct_cases"] = (
        len(dataset)
        - len(failures)
    )

    metrics["incorrect_cases"] = (
        len(failures)
    )

    metrics["failures"] = failures


    metrics["database_integrity"] = {

        "passed":
            database_integrity,

        "before":
            before_snapshot,

        "after":
            after_snapshot
    }


    return metrics


# ============================================================
# PRINT RESULTS
# ============================================================

def print_results(
    results
):

    print()

    print("=" * 80)

    print(
        "GUARDIANAGENT "
        "INDEPENDENT HELD-OUT V2 EVALUATION"
    )

    print("=" * 80)

    print()


    print(
        f"Dataset cases : "
        f"{results['total_cases']}"
    )

    print(
        "Intent mode   : GROUND-TRUTH"
    )

    print(
        "SQL execution : DISABLED"
    )

    print()


    # ========================================================
    # OVERALL
    # ========================================================

    print("=" * 80)

    print(
        "OVERALL PERFORMANCE"
    )

    print("=" * 80)

    print()


    print(
        f"Correct cases : "
        f"{results['correct_cases']}"
    )

    print(
        f"Incorrect cases : "
        f"{results['incorrect_cases']}"
    )

    print(
        f"Accuracy      : "
        f"{results['accuracy']:.2f}%"
    )

    print(
        f"Macro F1      : "
        f"{results['macro_f1']:.4f}"
    )

    print()


    # ========================================================
    # PER CLASS
    # ========================================================

    print("=" * 80)

    print(
        "PER-CLASS PERFORMANCE"
    )

    print("=" * 80)

    print()


    print(
        f"{'Decision':<15}"
        f"{'Precision':<15}"
        f"{'Recall':<15}"
        f"{'F1':<15}"
        f"{'Support':<10}"
    )

    print("-" * 70)


    for decision in DECISIONS:

        values = results[
            "per_class"
        ][decision]


        print(
            f"{decision:<15}"
            f"{values['precision']:<15.4f}"
            f"{values['recall']:<15.4f}"
            f"{values['f1']:<15.4f}"
            f"{values['support']:<10}"
        )


    print()


    # ========================================================
    # CONFUSION MATRIX
    # ========================================================

    print("=" * 80)

    print(
        "CONFUSION MATRIX"
    )

    print("=" * 80)

    print()

    print(
        "Labels: "
        + ", ".join(DECISIONS)
    )

    print()


    matrix = results[
        "confusion_matrix"
    ]["matrix"]


    print(
        "             Predicted"
    )

    print(
        "             "
        "ALLOW  CONFIRM  BLOCK"
    )


    for label, row in zip(
        DECISIONS,
        matrix
    ):

        print(
            f"Actual {label:<7}"
            f"{row[0]:<7}"
            f"{row[1]:<9}"
            f"{row[2]}"
        )


    print()


    # ========================================================
    # CATEGORY PERFORMANCE
    # ========================================================

    print("=" * 80)

    print(
        "CATEGORY-WISE PERFORMANCE"
    )

    print("=" * 80)

    print()


    print(
        f"{'Category':<32}"
        f"{'Correct':<12}"
        f"{'Total':<12}"
        f"{'Accuracy':<12}"
    )

    print("-" * 68)


    for category, values in (
        results[
            "category_results"
        ].items()
    ):

        print(
            f"{category:<32}"
            f"{values['correct']:<12}"
            f"{values['total']:<12}"
            f"{values['accuracy']:<12.2f}"
        )


    print()


    # ========================================================
    # SAFETY
    # ========================================================

    print("=" * 80)

    print(
        "SAFETY PERFORMANCE"
    )

    print("=" * 80)

    print()


    safety = results[
        "safety"
    ]


    print(
        "Dangerous cases not blocked : "
        f"{safety['dangerous_not_blocked']}"
    )


    print(
        "Safe cases incorrectly blocked : "
        f"{safety['safe_incorrectly_blocked']}"
    )


    print()


    # ========================================================
    # LATENCY
    # ========================================================

    print("=" * 80)

    print(
        "LATENCY"
    )

    print("=" * 80)

    print()


    latency = results[
        "latency_ms"
    ]


    print(
        f"Mean    : "
        f"{latency['mean']:.4f} ms"
    )


    print(
        f"Median  : "
        f"{latency['median']:.4f} ms"
    )


    print(
        f"Minimum : "
        f"{latency['minimum']:.4f} ms"
    )


    print(
        f"Maximum : "
        f"{latency['maximum']:.4f} ms"
    )


    print()


    # ========================================================
    # DATABASE INTEGRITY
    # ========================================================

    print("=" * 80)

    print(
        "DATABASE INTEGRITY"
    )

    print("=" * 80)

    print()


    if results[
        "database_integrity"
    ]["passed"]:

        print(
            "Database integrity : PASSED"
        )

    else:

        print(
            "Database integrity : FAILED"
        )


    print()


    # ========================================================
    # FAILURE DETAILS
    # ========================================================

    if results["failures"]:

        print("=" * 80)

        print(
            "FAILURE DETAILS"
        )

        print("=" * 80)

        print()


        for failure in results[
            "failures"
        ]:

            print(
                f"Case       : "
                f"{failure['case_id']}"
            )

            print(
                f"Category   : "
                f"{failure['category']}"
            )

            print(
                f"Expected   : "
                f"{failure['expected']}"
            )

            print(
                f"Predicted  : "
                f"{failure['predicted']}"
            )

            print(
                f"Risk score : "
                f"{failure['risk_score']}"
            )

            print(
                f"Risk level : "
                f"{failure['risk_level']}"
            )

            print(
                f"Request    : "
                f"{failure['user_request']}"
            )

            print(
                f"SQL        : "
                f"{failure['generated_sql']}"
            )

            print("-" * 80)


# ============================================================
# MAIN
# ============================================================

def main():

    results = run_benchmark()

    print_results(
        results
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
            results,
            file,
            indent=2,
            ensure_ascii=False
        )


    print()

    print("=" * 80)

    print(
        "RESULTS SAVED"
    )

    print("=" * 80)

    print()

    print(
        RESULTS_PATH
    )

    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()