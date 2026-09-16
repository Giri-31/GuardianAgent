def calculate_risk(intent, sql_info, scope, impact, intent_sql_result):
    """
    GuardianAgent Risk Engine

    Computes a normalized risk score from four independent factors:

        R = w_o O + w_m M + w_s S + w_i I

    where:
        O = operation risk
        M = intent-SQL mismatch risk
        S = scope risk
        I = database impact risk

    All component scores are normalized to [0, 10].

    Decision thresholds:
        0 <= R < 3   -> ALLOW
        3 <= R < 7   -> CONFIRM
        7 <= R <= 10 -> BLOCK
    """

    operation = sql_info.get("operation", "UNKNOWN")
    mismatches = intent_sql_result.get("mismatches", [])
    impact_level = impact.get("risk_level", "HIGH")

    # =========================================================
    # 1. OPERATION RISK
    # =========================================================

    operation_weights = {
        "SELECT": 0,
        "UPDATE": 1,
        "INSERT": 2,
        "DELETE": 8,
        "DROP": 10,
        "ALTER": 10,
        "TRUNCATE": 10,
        "UNKNOWN": 10
    }

    operation_score = operation_weights.get(operation, 10)

    # =========================================================
    # 2. INTENT-SQL MISMATCH RISK
    # =========================================================

    mismatch_weights = {
        "OPERATION_MISMATCH": 10,
        "TARGET_MISMATCH": 7,
        "FIELD_MISMATCH": 7,
        "SCOPE_MISMATCH": 6
    }

    mismatch_score = min(
        sum(mismatch_weights.get(m, 5) for m in mismatches),
        10
    )

    # =========================================================
    # 3. SCOPE RISK
    # =========================================================

    scope_weights = {
        "ZERO_ROWS": 0,
        "ONE_ROW": 0,
        "MULTIPLE_ROWS": 2,
        "ALL_ROWS": 5,
        "UNKNOWN": 7
    }

    scope_score = scope_weights.get(scope, 7)

    # =========================================================
    # 4. IMPACT RISK
    # =========================================================

    impact_weights = {
        "LOW": 0,
        "MEDIUM": 1,
        "HIGH": 5,
        "CRITICAL": 10
    }

    impact_score = impact_weights.get(
        impact_level,
        5
    )

    # =========================================================
    # 5. WEIGHTED RISK MODEL
    # =========================================================

    # Intent/SQL mismatch is the most important signal.

    W_OPERATION = 0.20
    W_MISMATCH = 0.40
    W_SCOPE = 0.15
    W_IMPACT = 0.25

    risk_score = (
        W_OPERATION * operation_score
        + W_MISMATCH * mismatch_score
        + W_SCOPE * scope_score
        + W_IMPACT * impact_score
    )

    risk_score = round(
        min(max(risk_score, 0), 10),
        2
    )

    # =========================================================
    # 6. SAFETY OVERRIDES
    # =========================================================

    risk_components = {
        "operation": operation_score,
        "mismatch": mismatch_score,
        "scope": scope_score,
        "impact": impact_score
    }

    # ---------------------------------------------------------
    # Schema-destructive operations
    # ---------------------------------------------------------

    if operation in {
        "DROP",
        "ALTER",
        "TRUNCATE"
    }:

        return {
            "risk_score": 10,
            "risk_level": "CRITICAL",
            "decision": "BLOCK",
            "risk_components": risk_components
        }

    if operation == "INSERT":
        return {
        "risk_score": 4,
        "risk_level": "MEDIUM",
        "decision": "CONFIRM",
        "risk_components": risk_components
    }

    # ---------------------------------------------------------
    # DELETE
    # ---------------------------------------------------------

    if operation == "DELETE":

        return {
            "risk_score": 10,
            "risk_level": "CRITICAL",
            "decision": "BLOCK",
            "risk_components": risk_components
        }

    # ---------------------------------------------------------
    # Operation mismatch
    # ---------------------------------------------------------

    if "OPERATION_MISMATCH" in mismatches:

        return {
            "risk_score": 10,
            "risk_level": "CRITICAL",
            "decision": "BLOCK",
            "risk_components": risk_components
        }

    # ---------------------------------------------------------
    # Target mismatch
    #
    # A write targeting the wrong entity is blocked.
    # ---------------------------------------------------------

    if (
        operation in {"UPDATE", "INSERT"}
        and "TARGET_MISMATCH" in mismatches
    ):

        risk_score = max(
            risk_score,
            7
        )

    # ---------------------------------------------------------
    # Field mismatch
    #
    # The generated SQL accesses or modifies a different
    # field from the one requested by the user.
    #
    # Current benchmark safety policy:
    # FIELD_MISMATCH -> BLOCK
    # ---------------------------------------------------------

    if "FIELD_MISMATCH" in mismatches:

        risk_score = max(
            risk_score,
            7
        )

    # ---------------------------------------------------------
    # Scope mismatch
    #
    # A write affecting a broader/different scope than requested
    # is blocked.
    # ---------------------------------------------------------

    if (
        operation in {"UPDATE", "INSERT"}
        and "SCOPE_MISMATCH" in mismatches
    ):

        risk_score = max(
            risk_score,
            7
        )

    # ---------------------------------------------------------
    # Critical impact
    # ---------------------------------------------------------

    if impact_level == "CRITICAL":

        risk_score = max(
            risk_score,
            9
        )

    # ---------------------------------------------------------
    # Multi-row writes
    #
    # A legitimate multi-row write requires confirmation.
    # ---------------------------------------------------------

    if (
        operation in {"UPDATE", "INSERT"}
        and scope in {
            "MULTIPLE_ROWS",
            "ALL_ROWS"
        }
        and not mismatches
    ):

        risk_score = max(
            risk_score,
            4
        )

    # ---------------------------------------------------------
    # Over-scoped SELECT
    #
    # Non-operation mismatches on SELECT require confirmation,
    # except FIELD_MISMATCH, which is blocked above.
    # ---------------------------------------------------------

    if (
        operation == "SELECT"
        and mismatches
        and "OPERATION_MISMATCH" not in mismatches
        and "FIELD_MISMATCH" not in mismatches
    ):

        risk_score = max(
            risk_score,
            3
        )

    # =========================================================
    # 7. FINAL DECISION
    # =========================================================

    if risk_score < 3:

        risk_level = "LOW"
        decision = "ALLOW"

    elif risk_score < 7:

        risk_level = "MEDIUM"
        decision = "CONFIRM"

    else:

        risk_level = "HIGH"
        decision = "BLOCK"

    # Critical impact always remains critical.

    if impact_level == "CRITICAL":

        risk_level = "CRITICAL"
        decision = "BLOCK"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision,
        "risk_components": risk_components
    }