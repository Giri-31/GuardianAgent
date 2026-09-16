import sys
import json
from pathlib import Path
from collections import Counter, defaultdict


# ============================================================
# PATH SETUP
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RESULTS_PATH = (
    ROOT
    / "benchmark"
    / "heldout_v2_results.json"
)

OUTPUT_PATH = (
    ROOT
    / "benchmark"
    / "heldout_v2_failure_analysis.json"
)


# ============================================================
# LOAD RESULTS
# ============================================================

with open(
    RESULTS_PATH,
    "r",
    encoding="utf-8"
) as file:

    results = json.load(file)


failures = results.get(
    "failures",
    []
)


# ============================================================
# BASIC COUNTS
# ============================================================

total_cases = results.get(
    "total_cases",
    0
)

incorrect_cases = len(
    failures
)


# ============================================================
# EXPECTED -> PREDICTED
# ============================================================

transition_counts = Counter()

for failure in failures:

    transition = (
        f"{failure['expected']} -> "
        f"{failure['predicted']}"
    )

    transition_counts[transition] += 1


# ============================================================
# CATEGORY COUNTS
# ============================================================

category_counts = Counter()

for failure in failures:

    category_counts[
        failure["category"]
    ] += 1


# ============================================================
# EXPECTED DECISION COUNTS
# ============================================================

expected_counts = Counter()

for failure in failures:

    expected_counts[
        failure["expected"]
    ] += 1


# ============================================================
# PREDICTED DECISION COUNTS
# ============================================================

predicted_counts = Counter()

for failure in failures:

    predicted_counts[
        failure["predicted"]
    ] += 1


# ============================================================
# RISK SCORE ANALYSIS
# ============================================================

risk_scores = []

for failure in failures:

    score = failure.get(
        "risk_score"
    )

    if score is not None:

        risk_scores.append(
            float(score)
        )


risk_score_distribution = Counter(
    risk_scores
)


# ============================================================
# RISK LEVEL ANALYSIS
# ============================================================

risk_level_counts = Counter()

for failure in failures:

    risk_level = failure.get(
        "risk_level",
        "UNKNOWN"
    )

    risk_level_counts[
        risk_level
    ] += 1


# ============================================================
# SCOPE ANALYSIS
# ============================================================

scope_counts = Counter()

for failure in failures:

    scope = failure.get(
        "scope",
        "UNKNOWN"
    )

    if isinstance(scope, dict):

        scope_name = scope.get(
            "scope",
            scope.get(
                "classification",
                str(scope)
            )
        )

    else:

        scope_name = str(scope)


    scope_counts[
        scope_name
    ] += 1


# ============================================================
# IMPACT ANALYSIS
# ============================================================

impact_counts = Counter()

for failure in failures:

    impact = failure.get(
        "impact",
        {}
    )


    if isinstance(impact, dict):

        impact_level = impact.get(
            "risk_level",
            "UNKNOWN"
        )

    else:

        impact_level = str(
            impact
        )


    impact_counts[
        impact_level
    ] += 1


# ============================================================
# INTENT-SQL MISMATCH ANALYSIS
# ============================================================

mismatch_counts = Counter()

for failure in failures:

    intent_sql = failure.get(
        "intent_sql",
        {}
    )


    if isinstance(intent_sql, dict):

        mismatches = intent_sql.get(
            "mismatches",
            []
        )

    else:

        mismatches = []


    if not mismatches:

        mismatch_counts[
            "NONE"
        ] += 1

    else:

        for mismatch in mismatches:

            mismatch_counts[
                mismatch
            ] += 1


# ============================================================
# FAILURE GROUPING
# ============================================================

failures_by_category = defaultdict(
    list
)

for failure in failures:

    failures_by_category[
        failure["category"]
    ].append(
        failure
    )


# ============================================================
# CATEGORY SUMMARY
# ============================================================

category_summary = {}


for category, items in sorted(
    failures_by_category.items()
):

    expected = Counter(
        item["expected"]
        for item in items
    )

    predicted = Counter(
        item["predicted"]
        for item in items
    )


    category_summary[category] = {

        "failure_count":
            len(items),

        "expected_decisions":
            dict(expected),

        "predicted_decisions":
            dict(predicted)
    }


# ============================================================
# SAFETY CLASSIFICATION
# ============================================================
#
# We distinguish:
#
# 1. Critical destructive operations
# 2. Other expected BLOCK cases
#
# This avoids treating every BLOCK expectation
# as a "dangerous database operation".
#
# ============================================================

critical_categories = {

    "DANGEROUS_DELETE",

    "DANGEROUS_DELETE_ALL",

    "DANGEROUS_DELETE_VARIANT",

    "DANGEROUS_MULTI_DELETE",

    "DANGEROUS_OPERATION"
}


critical_not_blocked = []

other_block_expected_not_blocked = []


for failure in failures:

    if (
        failure["expected"] == "BLOCK"
        and failure["predicted"] != "BLOCK"
    ):

        if failure["category"] in critical_categories:

            critical_not_blocked.append(
                failure
            )

        else:

            other_block_expected_not_blocked.append(
                failure
            )


# ============================================================
# SAFE CASES INCORRECTLY BLOCKED
# ============================================================

safe_incorrectly_blocked = []

for failure in failures:

    if (
        failure["expected"] == "ALLOW"
        and failure["predicted"] == "BLOCK"
    ):

        safe_incorrectly_blocked.append(
            failure
        )


# ============================================================
# CONFIRM CASES INCORRECTLY BLOCKED
# ============================================================

confirm_incorrectly_blocked = []

for failure in failures:

    if (
        failure["expected"] == "CONFIRM"
        and failure["predicted"] == "BLOCK"
    ):

        confirm_incorrectly_blocked.append(
            failure
        )


# ============================================================
# CONFIRM CASES INCORRECTLY ALLOWED
# ============================================================

confirm_incorrectly_allowed = []

for failure in failures:

    if (
        failure["expected"] == "CONFIRM"
        and failure["predicted"] == "ALLOW"
    ):

        confirm_incorrectly_allowed.append(
            failure
        )


# ============================================================
# FAILURE TYPE CLASSIFICATION
# ============================================================

failure_type_counts = Counter()


for failure in failures:

    expected = failure["expected"]

    predicted = failure["predicted"]

    category = failure["category"]


    if (
        expected == "BLOCK"
        and predicted == "CONFIRM"
    ):

        if category in critical_categories:

            failure_type = (
                "CRITICAL_OPERATION_NOT_BLOCKED"
            )

        else:

            failure_type = (
                "EXPECTED_BLOCK_PREDICTED_CONFIRM"
            )


    elif (
        expected == "BLOCK"
        and predicted == "ALLOW"
    ):

        failure_type = (
            "BLOCK_CASE_PREDICTED_ALLOW"
        )


    elif (
        expected == "ALLOW"
        and predicted == "BLOCK"
    ):

        failure_type = (
            "SAFE_CASE_PREDICTED_BLOCK"
        )


    elif (
        expected == "ALLOW"
        and predicted == "CONFIRM"
    ):

        failure_type = (
            "SAFE_CASE_PREDICTED_CONFIRM"
        )


    elif (
        expected == "CONFIRM"
        and predicted == "BLOCK"
    ):

        failure_type = (
            "CONFIRM_CASE_PREDICTED_BLOCK"
        )


    elif (
        expected == "CONFIRM"
        and predicted == "ALLOW"
    ):

        failure_type = (
            "CONFIRM_CASE_PREDICTED_ALLOW"
        )


    else:

        failure_type = (
            f"{expected}_TO_{predicted}"
        )


    failure_type_counts[
        failure_type
    ] += 1


# ============================================================
# REPRESENTATIVE FAILURES
# ============================================================

representative_failures = {}


for category, items in sorted(
    failures_by_category.items()
):

    # Keep the first failure as a representative
    # example for each failing category.

    representative = items[0]


    representative_failures[
        category
    ] = {

        "case_id":
            representative["case_id"],

        "user_request":
            representative["user_request"],

        "generated_sql":
            representative["generated_sql"],

        "expected":
            representative["expected"],

        "predicted":
            representative["predicted"],

        "risk_score":
            representative.get(
                "risk_score"
            ),

        "risk_level":
            representative.get(
                "risk_level"
            ),

        "scope":
            representative.get(
                "scope"
            ),

        "impact":
            representative.get(
                "impact"
            ),

        "intent_sql":
            representative.get(
                "intent_sql"
            )
    }


# ============================================================
# FULL ANALYSIS OBJECT
# ============================================================

analysis = {

    "experiment":
        "GuardianAgent Held-Out V2 Failure Analysis",

    "dataset":
        "benchmark/heldout_v2_dataset.json",

    "total_cases":
        total_cases,

    "incorrect_cases":
        incorrect_cases,

    "overall_accuracy":
        results.get(
            "accuracy"
        ),

    "macro_f1":
        results.get(
            "macro_f1"
        ),

    "failure_transitions":
        dict(
            transition_counts
        ),

    "failure_types":
        dict(
            failure_type_counts
        ),

    "failures_by_category":
        dict(
            category_counts
        ),

    "category_summary":
        category_summary,

    "expected_decisions_in_failures":
        dict(
            expected_counts
        ),

    "predicted_decisions_in_failures":
        dict(
            predicted_counts
        ),

    "risk_scores":
        {

            "distribution":
                dict(
                    risk_score_distribution
                ),

            "minimum":
                min(risk_scores)
                if risk_scores
                else None,

            "maximum":
                max(risk_scores)
                if risk_scores
                else None,

            "mean":
                (
                    sum(risk_scores)
                    / len(risk_scores)
                )
                if risk_scores
                else None
        },

    "risk_levels":
        dict(
            risk_level_counts
        ),

    "scope_values":
        dict(
            scope_counts
        ),

    "impact_levels":
        dict(
            impact_counts
        ),

    "intent_sql_mismatches":
        dict(
            mismatch_counts
        ),

    "safety_analysis":
        {

            "critical_operations_not_blocked":
                len(
                    critical_not_blocked
                ),

            "other_expected_block_cases_not_blocked":
                len(
                    other_block_expected_not_blocked
                ),

            "safe_cases_incorrectly_blocked":
                len(
                    safe_incorrectly_blocked
                ),

            "confirm_cases_incorrectly_blocked":
                len(
                    confirm_incorrectly_blocked
                ),

            "confirm_cases_incorrectly_allowed":
                len(
                    confirm_incorrectly_allowed
                )
        },

    "representative_failures":
        representative_failures,

    "all_failures":
        failures
}


# ============================================================
# SAVE ANALYSIS
# ============================================================

with open(
    OUTPUT_PATH,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        analysis,
        file,
        indent=2,
        ensure_ascii=False
    )


# ============================================================
# PRINT REPORT
# ============================================================

print()

print("=" * 80)

print(
    "GUARDIANAGENT V2 FAILURE ANALYSIS"
)

print("=" * 80)

print()


# ============================================================
# OVERALL
# ============================================================

print(
    "OVERALL"
)

print("-" * 80)

print(
    f"Total cases       : "
    f"{total_cases}"
)

print(
    f"Incorrect cases   : "
    f"{incorrect_cases}"
)

print(
    f"Accuracy          : "
    f"{results.get('accuracy', 0):.2f}%"
)

print(
    f"Macro F1          : "
    f"{results.get('macro_f1', 0):.4f}"
)

print()


# ============================================================
# FAILURE TRANSITIONS
# ============================================================

print(
    "FAILURE TRANSITIONS"
)

print("-" * 80)

print(
    f"{'Transition':<30}"
    f"{'Count':<10}"
)

print("-" * 40)


for transition, count in (
    transition_counts.most_common()
):

    print(
        f"{transition:<30}"
        f"{count:<10}"
    )


print()


# ============================================================
# FAILURE TYPES
# ============================================================

print(
    "FAILURE TYPES"
)

print("-" * 80)

print(
    f"{'Failure Type':<50}"
    f"{'Count':<10}"
)

print("-" * 60)


for failure_type, count in (
    failure_type_counts.most_common()
):

    print(
        f"{failure_type:<50}"
        f"{count:<10}"
    )


print()


# ============================================================
# FAILURES BY CATEGORY
# ============================================================

print(
    "FAILURES BY CATEGORY"
)

print("-" * 80)

print(
    f"{'Category':<35}"
    f"{'Failures':<10}"
)

print("-" * 50)


for category, count in (
    category_counts.most_common()
):

    print(
        f"{category:<35}"
        f"{count:<10}"
    )


print()


# ============================================================
# RISK LEVELS
# ============================================================

print(
    "RISK LEVELS AMONG FAILURES"
)

print("-" * 80)


for level, count in (
    risk_level_counts.most_common()
):

    print(
        f"{level:<15}"
        f"{count}"
    )


print()


# ============================================================
# SCOPE
# ============================================================

print(
    "SCOPE VALUES AMONG FAILURES"
)

print("-" * 80)


for scope, count in (
    scope_counts.most_common()
):

    print(
        f"{scope:<25}"
        f"{count}"
    )


print()


# ============================================================
# IMPACT
# ============================================================

print(
    "IMPACT LEVELS AMONG FAILURES"
)

print("-" * 80)


for impact, count in (
    impact_counts.most_common()
):

    print(
        f"{impact:<15}"
        f"{count}"
    )


print()


# ============================================================
# INTENT-SQL MISMATCHES
# ============================================================

print(
    "INTENT-SQL MISMATCHES AMONG FAILURES"
)

print("-" * 80)


for mismatch, count in (
    mismatch_counts.most_common()
):

    print(
        f"{mismatch:<30}"
        f"{count}"
    )


print()


# ============================================================
# SAFETY ANALYSIS
# ============================================================

print(
    "SAFETY ANALYSIS"
)

print("-" * 80)


print(
    "Critical operations not blocked : "
    f"{len(critical_not_blocked)}"
)


print(
    "Other expected BLOCK cases not blocked : "
    f"{len(other_block_expected_not_blocked)}"
)


print(
    "Safe cases incorrectly blocked : "
    f"{len(safe_incorrectly_blocked)}"
)


print(
    "CONFIRM cases incorrectly BLOCKED : "
    f"{len(confirm_incorrectly_blocked)}"
)


print(
    "CONFIRM cases incorrectly ALLOWED : "
    f"{len(confirm_incorrectly_allowed)}"
)


print()


# ============================================================
# REPRESENTATIVE FAILURES
# ============================================================

print(
    "REPRESENTATIVE FAILURE CASES"
)

print("=" * 80)


for category, failure in (
    representative_failures.items()
):

    print()

    print(
        f"Category : {category}"
    )

    print(
        f"Case     : {failure['case_id']}"
    )

    print(
        f"Expected : {failure['expected']}"
    )

    print(
        f"Predicted: {failure['predicted']}"
    )

    print(
        f"Risk     : {failure['risk_score']}"
    )

    print(
        f"Level    : {failure['risk_level']}"
    )

    print(
        f"Request  : {failure['user_request']}"
    )

    print(
        f"SQL      : {failure['generated_sql']}"
    )

    print("-" * 80)


# ============================================================
# SAVE LOCATION
# ============================================================

print()

print("=" * 80)

print(
    "ANALYSIS SAVED"
)

print("=" * 80)

print()

print(
    OUTPUT_PATH
)

print()