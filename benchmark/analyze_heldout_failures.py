import json
from pathlib import Path


# ============================================================
# HELD-OUT FAILURE ANALYSIS
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

RESULTS_PATH = (
    ROOT / "benchmark" / "heldout_results.json"
)

FAILURES_PATH = (
    ROOT / "benchmark" / "heldout_failures.json"
)


# ============================================================
# LOAD RESULTS
# ============================================================

def main():

    if not RESULTS_PATH.exists():

        raise FileNotFoundError(
            f"Results file not found:\n{RESULTS_PATH}"
        )

    with open(
        RESULTS_PATH,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    results = data.get(
        "results",
        []
    )

    # ========================================================
    # EXTRACT INCORRECT CASES
    # ========================================================

    failures = [
        result
        for result in results
        if not result["correct"]
    ]

    print()
    print("=" * 80)
    print("HELD-OUT BENCHMARK FAILURE ANALYSIS")
    print("=" * 80)

    print()
    print(
        f"Total evaluated : {len(results)}"
    )

    print(
        f"Incorrect cases : {len(failures)}"
    )

    print()

    # ========================================================
    # PRINT EVERY FAILURE
    # ========================================================

    for number, failure in enumerate(
        failures,
        start=1
    ):

        print("=" * 80)

        print(
            f"FAILURE {number}/{len(failures)}"
        )

        print("=" * 80)

        print(
            f"Case ID          : "
            f"{failure['case_id']}"
        )

        print(
            f"Category         : "
            f"{failure['category']}"
        )

        print()

        print(
            "User Request:"
        )

        print(
            failure["user_request"]
        )

        print()

        print(
            "Generated SQL:"
        )

        print(
            failure["generated_sql"]
        )

        print()

        print(
            f"Expected Decision : "
            f"{failure['expected_decision']}"
        )

        print(
            f"Predicted Decision: "
            f"{failure['predicted_decision']}"
        )

        print()

        print(
            f"Risk Score        : "
            f"{failure['risk_score']}"
        )

        print(
            f"Risk Level        : "
            f"{failure['risk_level']}"
        )

        print(
            f"Mismatches        : "
            f"{failure['mismatches']}"
        )

        print(
            f"Latency           : "
            f"{failure['latency_ms']} ms"
        )

        print()

    # ========================================================
    # CATEGORY SUMMARY
    # ========================================================

    category_failures = {}

    for failure in failures:

        category = failure["category"]

        category_failures[category] = (
            category_failures.get(
                category,
                0
            ) + 1
        )

    print("=" * 80)
    print("FAILURE SUMMARY BY CATEGORY")
    print("=" * 80)

    for category, count in sorted(
        category_failures.items()
    ):

        print(
            f"{category:<30} "
            f"{count}"
        )

    # ========================================================
    # DECISION ERROR SUMMARY
    # ========================================================

    decision_errors = {}

    for failure in failures:

        key = (
            failure["expected_decision"],
            failure["predicted_decision"]
        )

        decision_errors[key] = (
            decision_errors.get(
                key,
                0
            ) + 1
        )

    print()
    print("=" * 80)
    print("EXPECTED → PREDICTED ERRORS")
    print("=" * 80)

    for (
        expected,
        predicted
    ), count in sorted(
        decision_errors.items()
    ):

        print(
            f"{expected:<10} → "
            f"{predicted:<10} : "
            f"{count}"
        )

    # ========================================================
    # SAVE FAILURES
    # ========================================================

    with open(
        FAILURES_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            failures,
            file,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 80)

    print(
        f"Saved failures to:"
    )

    print(
        FAILURES_PATH
    )

    print("=" * 80)


if __name__ == "__main__":
    main()