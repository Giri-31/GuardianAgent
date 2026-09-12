def check_intent_sql(intent, sql_info, scope):
    mismatches = []

    operation = intent["operation"]
    target = intent["target"].lower()
    field = intent["field"].lower()
    intent_scope = intent["scope"].lower()

    where = str(sql_info["where"]).lower()
    sql_operation = sql_info["operation"]

    if operation != sql_operation:
        mismatches.append("OPERATION_MISMATCH")

    if target != "unknown":

        if target == "all employees":
            if sql_info["scope"] != "all_rows":
                mismatches.append("SCOPE_MISMATCH")

        elif target not in where:

            if sql_operation == "SELECT":
                mismatches.append("TARGET_MISMATCH")
            else:
                mismatches.append("TARGET_MISMATCH")

    if field != "unknown":

        if sql_operation in ["UPDATE", "INSERT"]:
            sql_lower = sql_info.get("sql", "").lower()

            if field not in sql_lower:
                mismatches.append("FIELD_MISMATCH")

    if intent_scope == "single employee":

        if scope != "ONE_ROW":
            mismatches.append("SCOPE_MISMATCH")

    elif intent_scope == "multiple employees":

        if scope == "ALL_ROWS" and target != "all employees":
            mismatches.append("SCOPE_MISMATCH")

    elif intent_scope == "all employees":

        if scope != "MULTIPLE_ROWS" and sql_info["scope"] != "all_rows":
            mismatches.append("SCOPE_MISMATCH")

    if mismatches:
        return {
            "status": "MISMATCH",
            "mismatches": mismatches
        }

    return {
        "status": "MATCH",
        "mismatches": []
    }