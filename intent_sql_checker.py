def check_intent_sql(intent, sql_info, scope):

    mismatches = []

    operation = intent["operation"]
    target = intent["target"].lower()
    field = intent["field"].lower()
    intent_scope = intent["scope"].lower()

    where = str(
        sql_info.get(
            "where",
            ""
        )
    ).lower()

    sql_operation = sql_info["operation"]

    sql_text = sql_info.get(
        "sql",
        ""
    ).lower()

    # =========================================================
    # 1. OPERATION CHECK
    # =========================================================

    if operation != sql_operation:

        mismatches.append(
            "OPERATION_MISMATCH"
        )

    # =========================================================
    # 2. TARGET CHECK
    # =========================================================

    if target != "unknown":

        # -----------------------------------------------------
        # ALL EMPLOYEES
        # -----------------------------------------------------

        if target == "all employees":

            if sql_info["scope"] != "all_rows":

                mismatches.append(
                    "SCOPE_MISMATCH"
                )

        # -----------------------------------------------------
        # INSERT
        #
        # INSERT has no WHERE clause.
        # Therefore check whether the intended target
        # appears in the INSERT statement itself.
        # -----------------------------------------------------

        elif sql_operation == "INSERT":

            if target not in sql_text:

                mismatches.append(
                    "TARGET_MISMATCH"
                )

        # -----------------------------------------------------
        # SELECT / UPDATE / DELETE
        # -----------------------------------------------------

        elif target not in where:

            mismatches.append(
                "TARGET_MISMATCH"
            )

    # =========================================================
    # 3. FIELD CHECK
    # =========================================================

    if field != "unknown":

        if field not in sql_text:

            mismatches.append(
                "FIELD_MISMATCH"
            )

    # =========================================================
    # 4. SCOPE CHECK
    # =========================================================

    if intent_scope == "single employee":

        if scope != "ONE_ROW":

            mismatches.append(
                "SCOPE_MISMATCH"
            )

    elif intent_scope == "multiple employees":

        if (
            scope == "ALL_ROWS"
            and target != "all employees"
        ):

            mismatches.append(
                "SCOPE_MISMATCH"
            )

    elif intent_scope == "all employees":

        if (
            scope != "MULTIPLE_ROWS"
            and sql_info["scope"] != "all_rows"
        ):

            mismatches.append(
                "SCOPE_MISMATCH"
            )

    # =========================================================
    # 5. RESULT
    # =========================================================

    if mismatches:

        return {
            "status": "MISMATCH",
            "mismatches": mismatches
        }

    return {
        "status": "MATCH",
        "mismatches": []
    }