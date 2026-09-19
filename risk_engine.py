"""
GuardianAgent Risk Engine

Consequence-aware risk scoring for SQL actions.

Design principles:
    - Schema-independent
    - No table/column/entity-specific rules
    - Weighted risk model
    - Explicit safety overrides
    - Legitimate state-changing inserts require confirmation
    - Broad legitimate writes require confirmation
    - Destructive operations are blocked
    - Unknown scope remains conservative
"""

# ---------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------

OPERATION_WEIGHT = 0.20
MISMATCH_WEIGHT = 0.40
SCOPE_WEIGHT = 0.15
IMPACT_WEIGHT = 0.25

MIN_RISK = 0.0
MAX_RISK = 10.0

ALLOW_THRESHOLD = 3.0
BLOCK_THRESHOLD = 7.0


# ---------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------

def _normalize_operation(operation):
    if operation is None:
        return "UNKNOWN"

    value = str(operation).strip().upper()

    aliases = {
        "READ": "SELECT",
        "WRITE": "UPDATE",
        "REMOVE": "DELETE",
    }

    return aliases.get(value, value)


def _normalize_scope(scope):
    if scope is None:
        return "UNKNOWN"

    value = str(scope).strip().upper()

    value = value.replace("-", "_")
    value = value.replace(" ", "_")

    aliases = {
        "SINGLE_ROW": "ONE_ROW",
        "SINGLE_ROWS": "ONE_ROW",
        "ONE": "ONE_ROW",
        "MULTIPLE_ROW": "MULTIPLE_ROWS",
        "MULTIPLE": "MULTIPLE_ROWS",
        "MANY_ROWS": "MULTIPLE_ROWS",
        "ALL": "ALL_ROWS",
        "ALL_ROW": "ALL_ROWS",
        "ZERO_ROW": "ZERO_ROWS",
        "NONE": "ZERO_ROWS",
    }

    value = aliases.get(value, value)

    if value in {
        "ZERO_ROWS",
        "ONE_ROW",
        "MULTIPLE_ROWS",
        "ALL_ROWS",
        "UNKNOWN",
    }:
        return value

    return "UNKNOWN"


def _normalize_risk_level(level):
    if level is None:
        return "HIGH"

    value = str(level).strip().upper()

    if value in {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }:
        return value

    return "HIGH"


# ---------------------------------------------------------------------
# Component scoring
# ---------------------------------------------------------------------

def _operation_score(operation):
    scores = {
        "SELECT": 0,
        "UPDATE": 1,
        "INSERT": 2,
        "DELETE": 8,
        "DROP": 10,
        "ALTER": 10,
        "TRUNCATE": 10,
        "UNKNOWN": 10,
    }

    return scores.get(
        operation,
        10
    )


def _mismatch_score(mismatches):
    if not mismatches:
        return 0

    weights = {
        "OPERATION_MISMATCH": 10,
        "TARGET_MISMATCH": 7,
        "FIELD_MISMATCH": 7,
        "VALUE_MISMATCH": 7,
        "SCOPE_MISMATCH": 6,
    }

    unknown_weight = 5

    return max(
        [
            weights.get(
                mismatch,
                unknown_weight
            )
            for mismatch in mismatches
        ],
        default=0
    )


def _scope_score(scope):
    scope_weights = {
        "ZERO_ROWS": 0,
        "ONE_ROW": 0,
        "MULTIPLE_ROWS": 2,
        "ALL_ROWS": 5,

        # Unknown scope remains conservative.
        "UNKNOWN": 7,
    }

    return scope_weights.get(
        scope,
        7
    )


def _impact_score(impact_level):
    impact_weights = {
        "LOW": 0,
        "MEDIUM": 1,
        "HIGH": 5,
        "CRITICAL": 10,
    }

    return impact_weights.get(
        impact_level,
        5
    )


# ---------------------------------------------------------------------
# Weighted risk
# ---------------------------------------------------------------------

def _calculate_weighted_score(
    operation_score,
    mismatch_score,
    scope_score,
    impact_score
):
    return (
        OPERATION_WEIGHT * operation_score
        + MISMATCH_WEIGHT * mismatch_score
        + SCOPE_WEIGHT * scope_score
        + IMPACT_WEIGHT * impact_score
    )


# ---------------------------------------------------------------------
# Safety overrides
# ---------------------------------------------------------------------

def _apply_safety_overrides(
    operation,
    mismatches,
    scope,
    impact_level,
    risk_score
):
    """
    Apply policy-level safety constraints.

    Policy distinction:

        Safe SELECT
            -> ALLOW

        Safe single-row UPDATE
            -> ALLOW

        Legitimate INSERT
            -> CONFIRM

        Legitimate broad UPDATE/INSERT
            -> CONFIRM

        DELETE
            -> BLOCK

        DROP / ALTER / TRUNCATE
            -> BLOCK

    Unknown scope remains conservative.
    """

    # ---------------------------------------------------------------
    # 1. Schema-destructive operations
    # ---------------------------------------------------------------

    if operation in {
        "DROP",
        "ALTER",
        "TRUNCATE",
    }:
        return 10.0

    # ---------------------------------------------------------------
    # 2. Operation mismatch
    # ---------------------------------------------------------------

    if "OPERATION_MISMATCH" in mismatches:
        return 10.0

    # ---------------------------------------------------------------
    # 3. DELETE
    # ---------------------------------------------------------------

    if operation == "DELETE":
        return 10.0

    # ---------------------------------------------------------------
    # 4. Write target mismatch
    # ---------------------------------------------------------------

    if (
        operation in {
            "UPDATE",
            "INSERT",
            "DELETE",
        }
        and "TARGET_MISMATCH" in mismatches
    ):
        risk_score = max(
            risk_score,
            7.0
        )

    # ---------------------------------------------------------------
    # 5. Field mismatch
    # ---------------------------------------------------------------

    if "FIELD_MISMATCH" in mismatches:
        risk_score = max(
            risk_score,
            7.0
        )

    # ---------------------------------------------------------------
    # 6. Value mismatch
    # ---------------------------------------------------------------

    if "VALUE_MISMATCH" in mismatches:
        risk_score = max(
            risk_score,
            7.0
        )

    # ---------------------------------------------------------------
    # 7. Scope mismatch on writes
    # ---------------------------------------------------------------

    if (
        operation in {
            "UPDATE",
            "INSERT",
            "DELETE",
        }
        and "SCOPE_MISMATCH" in mismatches
    ):
        risk_score = max(
            risk_score,
            7.0
        )

    # ---------------------------------------------------------------
    # 8. Critical impact
    #
    # Critical impact remains important, but legitimate broad
    # UPDATE/INSERT operations are handled explicitly below.
    # ---------------------------------------------------------------

    if impact_level == "CRITICAL":
        risk_score = max(
            risk_score,
            9.0
        )

    # ---------------------------------------------------------------
    # 9. Legitimate INSERT
    #
    # INSERT creates persistent database state even when it affects
    # only one row. Therefore, a consistent INSERT requires explicit
    # confirmation rather than automatic execution.
    #
    # This rule is schema-independent and does not depend on:
    #     - table name
    #     - column name
    #     - entity name
    #     - inserted values
    # ---------------------------------------------------------------

    if (
        operation == "INSERT"
        and not mismatches
    ):
        return max(
            min(
                risk_score,
                6.99
            ),
            4.0
        )

    # ---------------------------------------------------------------
    # 10. Legitimate broad writes
    #
    # If the user explicitly requested the broad operation and
    # intent-SQL consistency has no mismatch, require confirmation.
    #
    # This rule applies to UPDATE/INSERT.
    # INSERT is already handled above, but keeping it here documents
    # the broader policy explicitly.
    # ---------------------------------------------------------------

    if (
        operation in {
            "UPDATE",
            "INSERT",
        }
        and scope in {
            "MULTIPLE_ROWS",
            "ALL_ROWS",
        }
        and not mismatches
    ):
        return max(
            min(
                risk_score,
                6.99
            ),
            4.0
        )

    # ---------------------------------------------------------------
    # 11. SELECT mismatch
    #
    # Read mismatches generally require confirmation rather than
    # automatic blocking, except operation/field mismatches.
    # ---------------------------------------------------------------

    if (
        operation == "SELECT"
        and mismatches
        and "OPERATION_MISMATCH" not in mismatches
        and "FIELD_MISMATCH" not in mismatches
    ):
        risk_score = max(
            risk_score,
            3.0
        )

    return min(
        max(
            risk_score,
            MIN_RISK
        ),
        MAX_RISK
    )


# ---------------------------------------------------------------------
# Decision mapping
# ---------------------------------------------------------------------

def _decision_from_score(risk_score):
    if risk_score < ALLOW_THRESHOLD:
        return "LOW", "ALLOW"

    if risk_score < BLOCK_THRESHOLD:
        return "MEDIUM", "CONFIRM"

    return "HIGH", "BLOCK"


# ---------------------------------------------------------------------
# Result construction
# ---------------------------------------------------------------------

def _build_result(
    risk_score,
    risk_components,
    impact_level,
    operation=None,
    mismatches=None,
    scope=None
):
    """
    Build standardized GuardianAgent risk result.

    Legitimate INSERT operations require confirmation.

    Broad legitimate UPDATE/INSERT operations remain CONFIRM.

    Destructive operations remain BLOCK.
    """

    mismatches = mismatches or []

    risk_level, decision = _decision_from_score(
        risk_score
    )

    # Explicitly destructive operations remain blocked.
    if operation in {
        "DROP",
        "ALTER",
        "TRUNCATE",
        "DELETE",
    }:
        risk_level = "CRITICAL"
        decision = "BLOCK"

    # Legitimate INSERT operations require confirmation.
    elif (
        operation == "INSERT"
        and not mismatches
    ):
        risk_level = "MEDIUM"
        decision = "CONFIRM"

    # Legitimate broad UPDATE/INSERT operations require confirmation.
    elif (
        operation in {
            "UPDATE",
            "INSERT",
        }
        and scope in {
            "MULTIPLE_ROWS",
            "ALL_ROWS",
        }
        and not mismatches
    ):
        risk_level = "MEDIUM"
        decision = "CONFIRM"

    # Other critical impacts remain blocked.
    elif impact_level == "CRITICAL":
        risk_level = "CRITICAL"
        decision = "BLOCK"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision,
        "risk_components": risk_components,
    }


# ---------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------

def calculate_risk(
    intent,
    sql_info,
    scope,
    impact,
    intent_sql_result
):
    """
    Calculate GuardianAgent risk.

    The function combines:

        operation
        intent-SQL mismatch
        affected-row scope
        consequence/impact

    using a weighted risk model followed by explicit safety policies.
    """

    if not isinstance(intent, dict):
        intent = {}

    if not isinstance(sql_info, dict):
        sql_info = {}

    if not isinstance(impact, dict):
        impact = {}

    if not isinstance(intent_sql_result, dict):
        intent_sql_result = {}

    # ---------------------------------------------------------------
    # Normalize inputs
    # ---------------------------------------------------------------

    operation = _normalize_operation(
        sql_info.get(
            "operation",
            "UNKNOWN"
        )
    )

    normalized_scope = _normalize_scope(
        scope
    )

    impact_level = _normalize_risk_level(
        impact.get(
            "risk_level",
            "HIGH"
        )
    )

    mismatches = intent_sql_result.get(
        "mismatches",
        []
    )

    if not isinstance(mismatches, list):
        mismatches = [mismatches]

    mismatches = [
        str(mismatch).strip().upper()
        for mismatch in mismatches
        if str(mismatch).strip()
    ]

    mismatches = list(
        dict.fromkeys(
            mismatches
        )
    )

    # ---------------------------------------------------------------
    # Component scores
    # ---------------------------------------------------------------

    operation_score = _operation_score(
        operation
    )

    mismatch_score = _mismatch_score(
        mismatches
    )

    scope_score = _scope_score(
        normalized_scope
    )

    impact_score = _impact_score(
        impact_level
    )

    risk_components = {
        "operation": operation_score,
        "mismatch": mismatch_score,
        "scope": scope_score,
        "impact": impact_score,
    }

    # ---------------------------------------------------------------
    # Weighted risk
    # ---------------------------------------------------------------

    risk_score = _calculate_weighted_score(
        operation_score,
        mismatch_score,
        scope_score,
        impact_score
    )

    # ---------------------------------------------------------------
    # Safety policy
    # ---------------------------------------------------------------

    risk_score = _apply_safety_overrides(
        operation=operation,
        mismatches=mismatches,
        scope=normalized_scope,
        impact_level=impact_level,
        risk_score=risk_score
    )

    risk_score = round(
        min(
            max(
                risk_score,
                MIN_RISK
            ),
            MAX_RISK
        ),
        2
    )

    # ---------------------------------------------------------------
    # Final result
    # ---------------------------------------------------------------

    return _build_result(
        risk_score=risk_score,
        risk_components=risk_components,
        impact_level=impact_level,
        operation=operation,
        mismatches=mismatches,
        scope=normalized_scope
    )


# ---------------------------------------------------------------------
# Standalone tests
# ---------------------------------------------------------------------

def _run_tests():

    tests = [
        {
            "name": "Safe single-row update",
            "operation": "UPDATE",
            "scope": "ONE_ROW",
            "impact": "MEDIUM",
            "mismatches": [],
            "expected": "ALLOW",
        },
        {
            "name": "Legitimate single-row insert",
            "operation": "INSERT",
            "scope": "ONE_ROW",
            "impact": "LOW",
            "mismatches": [],
            "expected": "CONFIRM",
        },
        {
            "name": "Legitimate multi-row insert",
            "operation": "INSERT",
            "scope": "MULTIPLE_ROWS",
            "impact": "HIGH",
            "mismatches": [],
            "expected": "CONFIRM",
        },
        {
            "name": "Legitimate multi-row update",
            "operation": "UPDATE",
            "scope": "MULTIPLE_ROWS",
            "impact": "HIGH",
            "mismatches": [],
            "expected": "CONFIRM",
        },
        {
            "name": "Legitimate all-row update",
            "operation": "UPDATE",
            "scope": "ALL_ROWS",
            "impact": "CRITICAL",
            "mismatches": [],
            "expected": "CONFIRM",
        },
        {
            "name": "Wrong target update",
            "operation": "UPDATE",
            "scope": "ONE_ROW",
            "impact": "MEDIUM",
            "mismatches": ["TARGET_MISMATCH"],
            "expected": "BLOCK",
        },
        {
            "name": "Wrong field update",
            "operation": "UPDATE",
            "scope": "ONE_ROW",
            "impact": "MEDIUM",
            "mismatches": ["FIELD_MISMATCH"],
            "expected": "BLOCK",
        },
        {
            "name": "Wrong value update",
            "operation": "UPDATE",
            "scope": "ONE_ROW",
            "impact": "MEDIUM",
            "mismatches": ["VALUE_MISMATCH"],
            "expected": "BLOCK",
        },
        {
            "name": "Scope mismatch update",
            "operation": "UPDATE",
            "scope": "ALL_ROWS",
            "impact": "CRITICAL",
            "mismatches": ["SCOPE_MISMATCH"],
            "expected": "BLOCK",
        },
        {
            "name": "Delete one row",
            "operation": "DELETE",
            "scope": "ONE_ROW",
            "impact": "HIGH",
            "mismatches": [],
            "expected": "BLOCK",
        },
        {
            "name": "Delete all rows",
            "operation": "DELETE",
            "scope": "ALL_ROWS",
            "impact": "CRITICAL",
            "mismatches": [],
            "expected": "BLOCK",
        },
        {
            "name": "Drop table",
            "operation": "DROP",
            "scope": "UNKNOWN",
            "impact": "CRITICAL",
            "mismatches": [],
            "expected": "BLOCK",
        },
        {
            "name": "Safe select",
            "operation": "SELECT",
            "scope": "ONE_ROW",
            "impact": "LOW",
            "mismatches": [],
            "expected": "ALLOW",
        },
        {
            "name": "Mismatched select",
            "operation": "SELECT",
            "scope": "ONE_ROW",
            "impact": "LOW",
            "mismatches": ["TARGET_MISMATCH"],
            "expected": "CONFIRM",
        },
    ]

    print("=" * 70)
    print("GUARDIANAGENT RISK ENGINE TESTS")
    print("=" * 70)

    passed = 0

    for index, test in enumerate(tests, 1):

        result = calculate_risk(
            intent={},
            sql_info={
                "operation": test["operation"]
            },
            scope=test["scope"],
            impact={
                "risk_level": test["impact"]
            },
            intent_sql_result={
                "mismatches": test["mismatches"]
            }
        )

        actual = result["decision"]
        expected = test["expected"]

        ok = actual == expected

        print("\n" + "-" * 70)
        print(f"TEST {index}: {test['name']}")
        print(
            f"Expected: {expected} | "
            f"Actual: {actual}"
        )
        print(
            f"Risk score: {result['risk_score']}"
        )
        print(
            f"Risk level: {result['risk_level']}"
        )
        print(
            f"Components: {result['risk_components']}"
        )
        print("PASS" if ok else "FAIL")

        if ok:
            passed += 1

    print("\n" + "=" * 70)
    print(
        f"RESULT: {passed}/{len(tests)} tests passed"
    )
    print("=" * 70)


if __name__ == "__main__":
    _run_tests()