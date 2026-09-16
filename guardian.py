from google import genai
import os
import sqlite3

from sql_analyzer import analyze_sql
from intent_analyzer import analyze_intent
from risk_engine import calculate_risk
from intent_sql_checker import check_intent_sql

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def generate_sql(user_request):
    prompt = f"""
You are a SQL generator.

Database:
Table: employees

Columns:
id INTEGER
name TEXT
department TEXT
status TEXT
salary INTEGER

Convert the user's request into a SQLite SQL query.

User request:
{user_request}

Return ONLY the SQL query.
Do not use markdown.
Do not explain anything.
"""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )

    return response.text.strip()


def analyze_scope_safely(sql):
    """
    Safely estimate how many database rows a SQL statement affects.

    The SQL is NEVER executed directly.

    Scope categories:
        ZERO_ROWS
        ONE_ROW
        MULTIPLE_ROWS
        ALL_ROWS
        UNKNOWN

    Handles:
        SELECT
        UPDATE
        DELETE
        INSERT

    Supports qualified columns such as:
        e.name
        employees.name
    """

    import re
    import sqlite3

    sql_clean = sql.strip()
    sql_upper = sql_clean.upper()

    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    try:

        # =====================================================
        # INSERT
        # =====================================================
        #
        # INSERT does not use WHERE.
        # A normal single-row INSERT affects one row.
        #
        if sql_upper.startswith("INSERT"):

            values_match = re.search(
                r"\bVALUES\b(.+)",
                sql_clean,
                re.IGNORECASE | re.DOTALL
            )

            if not values_match:
                connection.close()
                return "UNKNOWN"

            values_part = (
                values_match.group(1)
                .rstrip(";")
                .strip()
            )

            # Count simple VALUES tuples.
            tuples = re.findall(
                r"\([^()]*\)",
                values_part
            )

            connection.close()

            if len(tuples) == 1:
                return "ONE_ROW"

            if len(tuples) > 1:
                return "MULTIPLE_ROWS"

            return "UNKNOWN"

        # =====================================================
        # Statements without WHERE
        # =====================================================

        if "WHERE" not in sql_upper:

            cursor.execute(
                "SELECT COUNT(*) FROM employees"
            )

            row_count = cursor.fetchone()[0]

            connection.close()

            if sql_upper.startswith("SELECT"):
                if row_count == 0:
                    return "ZERO_ROWS"

                if row_count == 1:
                    return "ONE_ROW"

                return "MULTIPLE_ROWS"

            # UPDATE / DELETE without WHERE affect all rows.
            if sql_upper.startswith(
                ("UPDATE", "DELETE")
            ):
                return "ALL_ROWS"

            return "UNKNOWN"

        # =====================================================
        # Extract WHERE condition
        # =====================================================

        where_match = re.search(
            r"\bWHERE\b(.+?)(?:;|$)",
            sql_clean,
            re.IGNORECASE | re.DOTALL
        )

        if not where_match:
            connection.close()
            return "UNKNOWN"

        where_condition = (
            where_match.group(1)
            .strip()
        )

        # =====================================================
        # Normalize qualified column names
        #
        # Example:
        #
        #     e.name = 'Arun'
        #
        # becomes:
        #
        #     name = 'Arun'
        #
        # This allows SQLite to evaluate the condition
        # against the employees table.
        # =====================================================

        where_condition = re.sub(
            r"\b[a-zA-Z_][a-zA-Z0-9_]*\.",
            "",
            where_condition
        )

        # =====================================================
        # Count matching rows
        # =====================================================

        count_query = (
            "SELECT COUNT(*) "
            "FROM employees "
            "WHERE "
            + where_condition
        )

        cursor.execute(count_query)

        row_count = cursor.fetchone()[0]

        connection.close()

        # =====================================================
        # Convert row count to scope
        # =====================================================

        if row_count == 0:
            return "ZERO_ROWS"

        if row_count == 1:
            return "ONE_ROW"

        return "MULTIPLE_ROWS"

    except Exception:
        connection.close()
        return "UNKNOWN"


def analyze_impact(sql, scope):
    operation = sql.split()[0].upper()

    if operation == "SELECT":
        return {
            "impact_type": "READ",
            "risk_level": "LOW"
        }

    if operation == "INSERT":
        return {
            "impact_type": "DATA_CREATION",
            "risk_level": "MEDIUM"
        }

    if operation == "UPDATE":
        if scope == "ONE_ROW":
            risk = "MEDIUM"
        elif scope == "MULTIPLE_ROWS":
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        return {
            "impact_type": "DATA_MODIFICATION",
            "risk_level": risk
        }

    if operation == "DELETE":
        if scope == "ONE_ROW":
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        return {
            "impact_type": "DATA_DELETION",
            "risk_level": risk
        }

    if operation == "DROP":
        return {
            "impact_type": "SCHEMA_DESTRUCTION",
            "risk_level": "CRITICAL"
        }

    return {
        "impact_type": "UNKNOWN",
        "risk_level": "HIGH"
    }


def guardian_check(user_request, sql, known_intent=None):
    if known_intent is not None:
        intent = known_intent
    else:
        intent = analyze_intent(user_request)

    sql_info = analyze_sql(sql)

    scope = analyze_scope_safely(sql)

    impact = analyze_impact(sql, scope)

    intent_sql_result = check_intent_sql(
    intent,
    sql_info,
    scope
)

    risk = calculate_risk(
    intent,
    sql_info,
    scope,
    impact,
    intent_sql_result
)

    return {
        "intent": intent,
        "sql_info": sql_info,
        "scope": scope,
        "impact": impact,
        "intent_sql": intent_sql_result,
        "risk": risk
    }


def execute_query(sql):
    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    cursor.execute(sql)

    if sql.strip().upper().startswith("SELECT"):
        result = cursor.fetchall()
    else:
        connection.commit()
        result = []

    connection.close()

    return result


def execute_with_guardian(user_request, sql):
    result = guardian_check(user_request, sql)

    decision = result["risk"]["decision"]

    print("\nGUARDIAN DECISION:", decision)

    if decision == "BLOCK":
        print("SQL BLOCKED.")
        return None

    if decision == "CONFIRM":
        print("SQL requires user confirmation.")

        answer = input("Do you want to execute this SQL? (yes/no): ")

        if answer.lower() != "yes":
            print("SQL execution cancelled.")
            return None

    if decision == "ALLOW":
        print("SQL automatically allowed.")

    print("Executing SQL...")

    return execute_query(sql)


if __name__ == "__main__":

    user_request = "Change Arun's salary to 70000."

    sql = generate_sql(user_request)

    print("\nUSER REQUEST:")
    print(user_request)

    print("\nGENERATED SQL:")
    print(sql)

    result = execute_with_guardian(
        user_request,
        sql
    )

    if result is not None:
        print("\nRESULT:")

        for row in result:
            print(row)