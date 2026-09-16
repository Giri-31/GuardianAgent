import json
import sys
import time
from pathlib import Path
from collections import defaultdict

from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix
)

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guardian import guardian_check
from rule_filter import rule_filter
from controlled_tests import tests


RESULTS_PATH = ROOT / "benchmark" / "baseline_results.json"


DECISIONS = [
    "ALLOW",
    "CONFIRM",
    "BLOCK"
]


def evaluate_system(name, predictions, expected, categories):
    """
    Evaluate one safety system.
    """

    accuracy = accuracy_score(
        expected,
        predictions
    )

    precision, recall, f1, support = (
        precision_recall_fscore_support(
            expected,
            predictions,
            labels=DECISIONS,
            zero_division=0
        )
    )

    matrix = confusion_matrix(
        expected,
        predictions,
        labels=DECISIONS
    )

    category_results = defaultdict(
        lambda: {
            "total": 0,
            "correct": 0
        }
    )

    for category, actual, prediction in zip(
        categories,
        expected,
        predictions
    ):

        category_results[category]["total"] += 1

        if actual == prediction:
            category_results[category]["correct"] += 1

    per_class = {}

    for i, decision in enumerate(DECISIONS):

        per_class[decision] = {
            "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4),
            "f1": round(float(f1[i]), 4),
            "support": int(support[i])
        }

    category_accuracy = {}

    for category, result in category_results.items():

        category_accuracy[category] = {
            "correct": result["correct"],
            "total": result["total"],
            "accuracy": round(
                (
                    result["correct"]
                    / result["total"]
                ) * 100,
                2
            )
        }

    return {
        "system": name,
        "total_cases": len(expected),
        "correct": int(
            sum(
                a == p
                for a, p in zip(
                    expected,
                    predictions
                )
            )
        ),
        "accuracy": round(
            float(accuracy) * 100,
            2
        ),
        "macro_f1": round(
            float(
                sum(f1) / len(f1)
            ),
            4
        ),
        "per_class": per_class,
        "confusion_matrix": {
            "labels": DECISIONS,
            "matrix": matrix.tolist()
        },
        "category_results": dict(
            category_accuracy
        )
    }


def run_comparison():

    expected = []
    categories = []

    normal_predictions = []
    rule_predictions = []
    guardian_predictions = []

    guardian_latencies = []

    print("=" * 80)
    print("GUARDIANAGENT BASELINE COMPARISON")
    print("=" * 80)

    print()
    print("Systems:")
    print("1. Always-Allow Baseline")
    print("2. SQL Rule Filter")
    print("3. GuardianAgent")

    print()
    print(f"Total cases : {len(tests)}")

    for test in tests:

        sql = test["sql"]

        expected.append(
            test["expected"]
        )

        categories.append(
            test["category"]
        )

        # --------------------------------------------------
        # BASELINE 1: ALWAYS ALLOW
        # --------------------------------------------------

        normal_decision = "ALLOW"

        normal_predictions.append(
            normal_decision
        )

        # --------------------------------------------------
        # BASELINE 2: RULE FILTER
        # --------------------------------------------------

        rule_decision = rule_filter(sql)

        rule_predictions.append(
            rule_decision
        )

        # --------------------------------------------------
        # GUARDIANAGENT
        # --------------------------------------------------

        start = time.perf_counter()

        guardian_result = guardian_check(
            test["request"],
            sql,
            known_intent=test["intent"]
        )

        elapsed_ms = (
            time.perf_counter() - start
        ) * 1000

        guardian_latencies.append(
            elapsed_ms
        )

        guardian_decision = (
            guardian_result["risk"]["decision"]
        )

        guardian_predictions.append(
            guardian_decision
        )

    # ------------------------------------------------------
    # EVALUATE
    # ------------------------------------------------------

    normal_results = evaluate_system(
        "Always-Allow",
        normal_predictions,
        expected,
        categories
    )

    rule_results = evaluate_system(
        "Rule Filter",
        rule_predictions,
        expected,
        categories
    )

    guardian_results = evaluate_system(
        "GuardianAgent",
        guardian_predictions,
        expected,
        categories
    )

    guardian_results["latency_ms"] = {
        "mean": round(
            sum(guardian_latencies)
            / len(guardian_latencies),
            4
        ),
        "median": round(
            sorted(guardian_latencies)[
                len(guardian_latencies) // 2
            ],
            4
        ),
        "minimum": round(
            min(guardian_latencies),
            4
        ),
        "maximum": round(
            max(guardian_latencies),
            4
        )
    }

    # ------------------------------------------------------
    # PRINT RESULTS
    # ------------------------------------------------------

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)

    print()
    print(
        f"{'System':<20}"
        f"{'Correct':<15}"
        f"{'Accuracy':<15}"
        f"{'Macro F1':<15}"
    )

    print("-" * 65)

    for result in [
        normal_results,
        rule_results,
        guardian_results
    ]:

        print(
            f"{result['system']:<20}"
            f"{result['correct']}/{result['total_cases']:<10}"
            f"{result['accuracy']:<15.2f}"
            f"{result['macro_f1']:<15.4f}"
        )

    # ------------------------------------------------------
    # PER-CLASS RESULTS
    # ------------------------------------------------------

    print()
    print("=" * 80)
    print("PER-CLASS F1")
    print("=" * 80)

    print()
    print(
        f"{'System':<20}"
        f"{'ALLOW':<15}"
        f"{'CONFIRM':<15}"
        f"{'BLOCK':<15}"
    )

    print("-" * 65)

    for result in [
        normal_results,
        rule_results,
        guardian_results
    ]:

        print(
            f"{result['system']:<20}"
            f"{result['per_class']['ALLOW']['f1']:<15.4f}"
            f"{result['per_class']['CONFIRM']['f1']:<15.4f}"
            f"{result['per_class']['BLOCK']['f1']:<15.4f}"
        )

    # ------------------------------------------------------
    # CATEGORY RESULTS
    # ------------------------------------------------------

    print()
    print("=" * 80)
    print("CATEGORY-WISE ACCURACY")
    print("=" * 80)

    all_categories = sorted(
        set(categories)
    )

    print()

    print(
        f"{'Category':<25}"
        f"{'Always-Allow':<18}"
        f"{'Rule Filter':<18}"
        f"{'GuardianAgent':<18}"
    )

    print("-" * 80)

    for category in all_categories:

        normal_category = (
            normal_results[
                "category_results"
            ].get(category)
        )

        rule_category = (
            rule_results[
                "category_results"
            ].get(category)
        )

        guardian_category = (
            guardian_results[
                "category_results"
            ].get(category)
        )

        normal_acc = (
            normal_category["accuracy"]
            if normal_category
            else 0
        )

        rule_acc = (
            rule_category["accuracy"]
            if rule_category
            else 0
        )

        guardian_acc = (
            guardian_category["accuracy"]
            if guardian_category
            else 0
        )

        print(
            f"{category:<25}"
            f"{normal_acc:<18.2f}"
            f"{rule_acc:<18.2f}"
            f"{guardian_acc:<18.2f}"
        )

    # ------------------------------------------------------
    # SAFETY ERROR ANALYSIS
    # ------------------------------------------------------

    print()
    print("=" * 80)
    print("SAFETY ERROR ANALYSIS")
    print("=" * 80)

    for name, predictions in [
        ("Always-Allow", normal_predictions),
        ("Rule Filter", rule_predictions),
        ("GuardianAgent", guardian_predictions)
    ]:

        dangerous_allowed = 0
        safe_blocked = 0

        for actual, prediction in zip(
            expected,
            predictions
        ):

            if actual == "BLOCK" and prediction != "BLOCK":
                dangerous_allowed += 1

            if actual == "ALLOW" and prediction == "BLOCK":
                safe_blocked += 1

        print()
        print(name)
        print(
            "Dangerous cases not blocked :",
            dangerous_allowed
        )
        print(
            "Safe cases incorrectly blocked:",
            safe_blocked
        )

    # ------------------------------------------------------
    # SAVE RESULTS
    # ------------------------------------------------------

    output = {
        "experiment": "Baseline Comparison",
        "dataset": "controlled_tests.py",
        "total_cases": len(tests),
        "systems": {
            "always_allow": normal_results,
            "rule_filter": rule_results,
            "guardianagent": guardian_results
        }
    }

    RESULTS_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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

    print()
    print("=" * 80)
    print("RESULTS SAVED")
    print("=" * 80)

    print(
        RESULTS_PATH
    )


if __name__ == "__main__":
    run_comparison()