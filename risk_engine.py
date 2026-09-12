def calculate_risk(intent, sql_info, scope, impact, intent_sql_result):

    operation = sql_info["operation"]
    mismatches = intent_sql_result["mismatches"]

    risk_score = 0

    if operation in ["DROP", "ALTER", "TRUNCATE"]:
        return {
            "risk_score": 10,
            "risk_level": "HIGH",
            "decision": "BLOCK"
        }

    if operation == "DELETE":
        return {
            "risk_score": 10,
            "risk_level": "HIGH",
            "decision": "BLOCK"
        }

    if "OPERATION_MISMATCH" in mismatches:
        return {
            "risk_score": 10,
            "risk_level": "HIGH",
            "decision": "BLOCK"
        }

    if "TARGET_MISMATCH" in mismatches:
        if operation == "SELECT":
            return {
                "risk_score": 3,
                "risk_level": "MEDIUM",
                "decision": "CONFIRM"
            }

        return {
            "risk_score": 10,
            "risk_level": "HIGH",
            "decision": "BLOCK"
        }

    if "FIELD_MISMATCH" in mismatches:
        return {
            "risk_score": 10,
            "risk_level": "HIGH",
            "decision": "BLOCK"
        }

    if "SCOPE_MISMATCH" in mismatches:

        if operation == "SELECT":
            return {
                "risk_score": 3,
                "risk_level": "MEDIUM",
                "decision": "CONFIRM"
            }

        return {
            "risk_score": 10,
            "risk_level": "HIGH",
            "decision": "BLOCK"
        }

    if operation == "UPDATE":

        if scope == "ONE_ROW":
            return {
                "risk_score": 0,
                "risk_level": "LOW",
                "decision": "ALLOW"
            }

        return {
            "risk_score": 3,
            "risk_level": "MEDIUM",
            "decision": "CONFIRM"
        }

    if operation == "INSERT":
        return {
            "risk_score": 3,
            "risk_level": "MEDIUM",
            "decision": "CONFIRM"
        }

    if operation == "SELECT":

        return {
            "risk_score": 0,
            "risk_level": "LOW",
            "decision": "ALLOW"
        }

    return {
        "risk_score": 10,
        "risk_level": "HIGH",
        "decision": "BLOCK"
    }