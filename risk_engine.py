def calculate_risk(intent, sql_info, scope, impact):
    risk_score = 0

    if intent["operation"] != sql_info["operation"]:
        risk_score += 4

    if intent["scope"] == "single employee" and scope == "MULTIPLE_ROWS":
        risk_score += 4

    if intent["scope"] == "single employee" and scope == "ALL_ROWS":
        risk_score += 5

    if impact["risk_level"] == "LOW":
        risk_score += 0

    elif impact["risk_level"] == "MEDIUM":
        risk_score += 2

    elif impact["risk_level"] == "HIGH":
        risk_score += 4

    elif impact["risk_level"] == "CRITICAL":
        risk_score += 6

    if risk_score >= 6:
        risk_level = "HIGH"
        decision = "BLOCK"

    elif risk_score >= 3:
        risk_level = "MEDIUM"
        decision = "CONFIRM"

    else:
        risk_level = "LOW"
        decision = "ALLOW"

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision
    }


if __name__ == "__main__":

    intent = {
        "operation": "UPDATE",
        "target": "Arun",
        "field": "salary",
        "value": "70000",
        "scope": "single employee"
    }

    sql_info = {
        "operation": "UPDATE",
        "table": "employees",
        "where": "name = 'Arun'",
        "scope": "filtered"
    }

    scope = "ONE_ROW"

    impact = {
        "impact_type": "DATA_MODIFICATION",
        "risk_level": "MEDIUM"
    }

    result = calculate_risk(
        intent,
        sql_info,
        scope,
        impact
    )

    print("Risk result:", result)