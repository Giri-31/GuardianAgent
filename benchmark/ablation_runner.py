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
# PATH SETUP
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# GUARDIANAGENT IMPORTS
# ============================================================

from guardian import guardian_check
from sql_analyzer import analyze_sql
from intent_sql_checker import check_intent_sql
from risk_engine import calculate_risk


# ============================================================
# DATASET PATHS
# ============================================================

DATASET_PATH = ROOT / "benchmark" / "heldout_dataset.json"
RESULTS_PATH = ROOT / "benchmark" / "ablation_results.json"


# ============================================================
# LOAD DATASET
# ============================================================

with open(DATASET_PATH, "r", encoding="utf-8") as file:
    dataset = json.load(file)


# ============================================================
# DECISION LABELS
# ============================================================

DECISIONS = [
    "ALLOW",
    "CONFIRM",
    "BLOCK"
]


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(expected, predicted):

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

    for i, decision in enumerate(DECISIONS):

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

def category_metrics(
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

    for category, values in results.items():

        output[category] = {

            "correct": values["correct"],

            "total": values["total"],

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

def safety_metrics(
    expected,
    predicted
):

    dangerous_not_blocked = 0

    safe_incorrectly_blocked = 0

    for actual, prediction in zip(
        expected,
        predicted
    ):

        # A dangerous case is expected to be BLOCK.
        # If it receives ALLOW or CONFIRM, it was not blocked.
        if (
            actual == "BLOCK"
            and prediction != "BLOCK"
        ):
            dangerous_not_blocked += 1

        # A safe case is expected to be ALLOW.
        # BLOCK is therefore an incorrect blocking decision.
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
# ABLATION FUNCTION
# ============================================================

def ablated_guardian(
    test,
    mode
):

    # --------------------------------------------------------
    # DATASET FIELDS
    # --------------------------------------------------------

    request = test["user_request"]

    sql = test["generated_sql"]

    intent = test["ground_truth_intent"]


    # --------------------------------------------------------
    # SQL ANALYSIS
    # --------------------------------------------------------

    sql_info = analyze_sql(sql)


    # ========================================================
    # FULL GUARDIANAGENT
    # ========================================================

    if mode == "FULL":

        result = guardian_check(
            request,
            sql,
            known_intent=intent
        )

        return result["risk"]["decision"]


    # ========================================================
    # COMMON COMPONENTS
    # ========================================================

    full_result = guardian_check(
        request,
        sql,
        known_intent=intent
    )

    scope = full_result["scope"]

    impact = full_result["impact"]


    # ========================================================
    # ABLATION 1
    # WITHOUT INTENT-SQL CHECKER
    # ========================================================

    if mode == "NO_INTENT_SQL":

        # Remove the intent-SQL consistency signal.

        neutral_intent_sql = {
            "status": "MATCH",
            "mismatches": []
        }

        risk = calculate_risk(
            intent,
            sql_info,
            scope,
            impact,
            neutral_intent_sql
        )

        return risk["decision"]


    # ========================================================
    # ABLATION 2
    # WITHOUT SCOPE ANALYSIS
    # ========================================================

    if mode == "NO_SCOPE":

        # First obtain the normal intent-SQL result.

        intent_sql = check_intent_sql(
            intent,
            sql_info,
            scope
        )

        # Remove scope mismatch from the consistency
        # signal so scope information is completely
        # excluded from this ablation.

        intent_sql["mismatches"] = [
            mismatch
            for mismatch in intent_sql["mismatches"]
            if mismatch != "SCOPE_MISMATCH"
        ]

        if intent_sql["mismatches"]:

            intent_sql["status"] = "MISMATCH"

        else:

            intent_sql["status"] = "MATCH"


        # UNKNOWN scope removes the scope-risk contribution.

        risk = calculate_risk(
            intent,
            sql_info,
            "UNKNOWN",
            impact,
            intent_sql
        )

        return risk["decision"]


    # ========================================================
    # ABLATION 3
    # WITHOUT DATABASE IMPACT
    # ========================================================

    if mode == "NO_IMPACT":

        intent_sql = check_intent_sql(
            intent,
            sql_info,
            scope
        )

        # Neutral LOW impact removes the contribution
        # of database-impact analysis.

        neutral_impact = {

            "impact_type": "UNKNOWN",

            "risk_level": "LOW"
        }

        risk = calculate_risk(
            intent,
            sql_info,
            scope,
            neutral_impact,
            intent_sql
        )

        return risk["decision"]


    # ========================================================
    # ABLATION 4
    # WITHOUT USER INTENT
    # ========================================================

    if mode == "NO_INTENT":

        # We remove semantic intent information.
        #
        # IMPORTANT:
        # We retain the SQL operation so that the
        # ablation does not artificially create an
        # OPERATION_MISMATCH for every test case.

        intent_without_semantics = {

            "operation":
                sql_info["operation"],

            "target":
                "unknown",

            "field":
                "unknown",

            "value":
                "unknown",

            "scope":
                "unknown"
        }


        # Since user intent is unavailable,
        # no intent-SQL consistency information
        # is supplied.

        neutral_intent_sql = {

            "status": "MATCH",

            "mismatches": []
        }


        risk = calculate_risk(
            intent_without_semantics,
            sql_info,
            scope,
            impact,
            neutral_intent_sql
        )

        return risk["decision"]


    # ========================================================
    # INVALID MODE
    # ========================================================

    raise ValueError(
        f"Unknown ablation mode: {mode}"
    )


# ============================================================
# RUN ONE ABLATION
# ============================================================

def run_ablation(mode):

    expected = []

    predicted = []

    categories = []

    latencies = []


    # --------------------------------------------------------
    # PROCESS ALL DATASET CASES
    # --------------------------------------------------------

    for test in dataset:

        # Correct held-out dataset field:
        # expected_decision

        expected.append(
            test["expected_decision"]
        )

        categories.append(
            test["category"]
        )


        # ----------------------------------------------------
        # LATENCY
        # ----------------------------------------------------

        start = time.perf_counter()


        # ----------------------------------------------------
        # DECISION
        # ----------------------------------------------------

        decision = ablated_guardian(
            test,
            mode
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

        predicted.append(
            decision
        )


    # ========================================================
    # CALCULATE METRICS
    # ========================================================

    metrics = calculate_metrics(
        expected,
        predicted
    )


    # ========================================================
    # CATEGORY RESULTS
    # ========================================================

    metrics["category_results"] = (
        category_metrics(
            expected,
            predicted,
            categories
        )
    )


    # ========================================================
    # SAFETY RESULTS
    # ========================================================

    metrics["safety"] = safety_metrics(
        expected,
        predicted
    )


    # ========================================================
    # LATENCY RESULTS
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


    return metrics


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)

    print(
        "GUARDIANAGENT ABLATION STUDY"
    )

    print("=" * 80)

    print()


    # ========================================================
    # DATASET INFORMATION
    # ========================================================

    print(
        f"Dataset cases : {len(dataset)}"
    )

    print(
        "Intent mode   : GROUND-TRUTH"
    )

    print(
        "SQL execution : DISABLED"
    )

    print()


    # ========================================================
    # ABLATION CONFIGURATIONS
    # ========================================================

    modes = {

        "FULL":
            "Full GuardianAgent",

        "NO_INTENT_SQL":
            "Without Intent-SQL Checker",

        "NO_SCOPE":
            "Without Scope Analysis",

        "NO_IMPACT":
            "Without Database Impact",

        "NO_INTENT":
            "Without User Intent"
    }


    results = {}


    # ========================================================
    # RUN EXPERIMENTS
    # ========================================================

    for mode, name in modes.items():

        print(
            f"Running: {name}..."
        )


        results[mode] = run_ablation(
            mode
        )


        print(
            f"Accuracy: "
            f"{results[mode]['accuracy']:.2f}%"
        )


        print(
            f"Macro F1: "
            f"{results[mode]['macro_f1']:.4f}"
        )


        print()


    # ========================================================
    # SUMMARY TABLE
    # ========================================================

    print("=" * 80)

    print(
        "ABLATION RESULTS"
    )

    print("=" * 80)

    print()


    print(
        f"{'Configuration':<35}"
        f"{'Accuracy':<15}"
        f"{'Macro F1':<15}"
    )

    print("-" * 65)


    for mode, name in modes.items():

        result = results[mode]

        print(
            f"{name:<35}"
            f"{result['accuracy']:<15.2f}"
            f"{result['macro_f1']:<15.4f}"
        )


    print()


    # ========================================================
    # SAFETY ERROR TABLE
    # ========================================================

    print("=" * 80)

    print(
        "SAFETY ERROR COMPARISON"
    )

    print("=" * 80)

    print()


    print(
        f"{'Configuration':<35}"
        f"{'Dangerous Not Blocked':<25}"
        f"{'Safe Incorrectly Blocked':<25}"
    )

    print("-" * 85)


    for mode, name in modes.items():

        safety = results[mode]["safety"]


        print(
            f"{name:<35}"
            f"{safety['dangerous_not_blocked']:<25}"
            f"{safety['safe_incorrectly_blocked']:<25}"
        )


    print()


    # ========================================================
    # LATENCY TABLE
    # ========================================================

    print("=" * 80)

    print(
        "LATENCY COMPARISON"
    )

    print("=" * 80)

    print()


    print(
        f"{'Configuration':<35}"
        f"{'Mean (ms)':<15}"
        f"{'Median (ms)':<15}"
        f"{'Max (ms)':<15}"
    )

    print("-" * 80)


    for mode, name in modes.items():

        latency = results[mode]["latency_ms"]


        print(
            f"{name:<35}"
            f"{latency['mean']:<15.4f}"
            f"{latency['median']:<15.4f}"
            f"{latency['maximum']:<15.4f}"
        )


    print()


    # ========================================================
    # SAVE RESULTS
    # ========================================================

    output = {

        "experiment":
            "GuardianAgent Component Ablation",

        "dataset":
            "benchmark/heldout_dataset.json",

        "total_cases":
            len(dataset),

        "intent_mode":
            "GROUND-TRUTH",

        "sql_execution":
            False,

        "configurations":
            results
    }


    with open(
        RESULTS_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2
        )


    # ========================================================
    # COMPLETION
    # ========================================================

    print("=" * 80)

    print(
        "RESULTS SAVED"
    )

    print("=" * 80)

    print()

    print(
        RESULTS_PATH
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()