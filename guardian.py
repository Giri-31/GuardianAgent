from google import genai
import os
import sqlite3

from sql_analyzer import analyze_sql
from intent_analyzer import analyze_intent
from risk_engine import calculate_risk
from intent_sql_checker import check_intent_sql


# ============================================================
# Gemini Client
# ============================================================

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# ============================================================
# SQL Generation
# ============================================================

def generate_sql(user_request):
    """
    Generate SQL for the original GuardianAgent demo
    using the company.db employees schema.

    DBBench uses its own SQL-generation pipeline.
    """

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


# ============================================================
# Safe Scope Analysis
# ============================================================

def analyze_scope_safely(
    sql,
    connection=None,
    table_name="employees"
):
    """
    Estimate how many database rows a SQL statement targets.

    Scope categories:

        ZERO_ROWS
        ONE_ROW
        MULTIPLE_ROWS
        ALL_ROWS
        UNKNOWN

    The input SQL is NOT directly executed.

    Parameters
    ----------
    sql:
        SQL statement being analyzed.

    connection:
        Optional SQLite database connection.

        If None:
            company.db is opened.

        If provided:
            the supplied database is used.

    table_name:
        Table against which the scope should be evaluated.

        Defaults to employees so existing GuardianAgent
        experiments remain unchanged.
    """

    import re

    if not sql:
        return "UNKNOWN"

    sql_clean = str(
        sql
    ).strip()

    if not sql_clean:
        return "UNKNOWN"

    sql_upper = sql_clean.upper()

    owns_connection = (
        connection is None
    )

    # --------------------------------------------------------
    # Existing GuardianAgent behavior
    # --------------------------------------------------------

    if owns_connection:

        connection = sqlite3.connect(
            "company.db"
        )

    cursor = connection.cursor()

    # --------------------------------------------------------
    # Quote table identifier safely
    # --------------------------------------------------------

    def quote_identifier(name):

        return (
            '"'
            + str(name).replace(
                '"',
                '""'
            )
            + '"'
        )

    qualified_table = quote_identifier(
        table_name
    )

    try:

        # ====================================================
        # INSERT
        # ====================================================

        if sql_upper.startswith(
            "INSERT"
        ):

            values_match = re.search(
                r"\bVALUES\b(.+)",
                sql_clean,
                re.IGNORECASE |
                re.DOTALL
            )

            if not values_match:
                return "UNKNOWN"

            values_part = (
                values_match
                .group(1)
                .rstrip(";")
                .strip()
            )

            # Count simple VALUES tuples.
            #
            # Example:
            #
            # VALUES ('A', 10)
            #
            # -> ONE_ROW
            #
            # VALUES ('A',10), ('B',20)
            #
            # -> MULTIPLE_ROWS

            tuples = re.findall(
                r"\([^()]*\)",
                values_part
            )

            if len(tuples) == 1:
                return "ONE_ROW"

            if len(tuples) > 1:
                return "MULTIPLE_ROWS"

            return "UNKNOWN"

        # ====================================================
        # SELECT / UPDATE / DELETE without WHERE
        # ====================================================

        if "WHERE" not in sql_upper:

            # ------------------------------------------------
            # SELECT without WHERE
            # ------------------------------------------------

            if sql_upper.startswith(
                "SELECT"
            ):

                cursor.execute(
                    "SELECT COUNT(*) FROM "
                    + qualified_table
                )

                row_count = (
                    cursor.fetchone()[0]
                )

                if row_count == 0:
                    return "ZERO_ROWS"

                if row_count == 1:
                    return "ONE_ROW"

                return "MULTIPLE_ROWS"

            # ------------------------------------------------
            # UPDATE / DELETE without WHERE
            # ------------------------------------------------

            if sql_upper.startswith(
                (
                    "UPDATE",
                    "DELETE"
                )
            ):

                return "ALL_ROWS"

            return "UNKNOWN"

        # ====================================================
        # Extract WHERE condition
        # ====================================================

        where_match = re.search(
            r"\bWHERE\b(.+?)(?:;|$)",
            sql_clean,
            re.IGNORECASE |
            re.DOTALL
        )

        if not where_match:
            return "UNKNOWN"

        where_condition = (
            where_match
            .group(1)
            .strip()
        )

        # ----------------------------------------------------
        # Remove simple table aliases
        #
        # e.name
        # employees.name
        #
        # becomes:
        #
        # name
        # ----------------------------------------------------

        where_condition = re.sub(
            r"\b[a-zA-Z_][a-zA-Z0-9_]*\.",
            "",
            where_condition
        )

        # ====================================================
        # Count matching rows
        # ====================================================

        count_query = (
            "SELECT COUNT(*) FROM "
            + qualified_table
            + " WHERE "
            + where_condition
        )

        cursor.execute(
            count_query
        )

        row_count = (
            cursor.fetchone()[0]
        )

        # ====================================================
        # Convert count to scope
        # ====================================================

        if row_count == 0:
            return "ZERO_ROWS"

        if row_count == 1:
            return "ONE_ROW"

        return "MULTIPLE_ROWS"

    except Exception:

        return "UNKNOWN"

    finally:

        if owns_connection:

            try:
                connection.close()

            except Exception:
                pass


# ============================================================
# Database Impact Analysis
# ============================================================

def analyze_impact(
    sql,
    scope
):
    """
    Estimate the potential impact of a SQL statement.

    This function is schema-independent.

    It does NOT:

        - know any table names
        - know any column names
        - connect to company.db
        - execute SQL

    It uses:

        SQL operation
        estimated scope
    """

    sql_info = analyze_sql(
        sql
    )

    operation = sql_info.get(
        "operation",
        "UNKNOWN"
    )

    # ========================================================
    # SELECT
    # ========================================================

    if operation == "SELECT":

        return {
            "impact_type": "READ",
            "risk_level": "LOW"
        }

    # ========================================================
    # INSERT
    # ========================================================

    if operation == "INSERT":

        if scope == "MULTIPLE_ROWS":

            risk = "HIGH"

        elif scope == "ONE_ROW":

            risk = "MEDIUM"

        else:

            risk = "MEDIUM"

        return {
            "impact_type": "DATA_CREATION",
            "risk_level": risk
        }

    # ========================================================
    # UPDATE
    # ========================================================

    if operation == "UPDATE":

        if scope == "ONE_ROW":

            risk = "MEDIUM"

        elif scope == "MULTIPLE_ROWS":

            risk = "HIGH"

        elif scope == "ZERO_ROWS":

            risk = "LOW"

        elif scope == "ALL_ROWS":

            risk = "CRITICAL"

        else:

            risk = "HIGH"

        return {
            "impact_type": "DATA_MODIFICATION",
            "risk_level": risk
        }

    # ========================================================
    # DELETE
    # ========================================================

    if operation == "DELETE":

        if scope == "ZERO_ROWS":

            risk = "LOW"

        elif scope == "ONE_ROW":

            risk = "HIGH"

        else:

            risk = "CRITICAL"

        return {
            "impact_type": "DATA_DELETION",
            "risk_level": risk
        }

    # ========================================================
    # DROP
    # ========================================================

    if operation == "DROP":

        return {
            "impact_type": "SCHEMA_DESTRUCTION",
            "risk_level": "CRITICAL"
        }

    # ========================================================
    # ALTER
    # ========================================================

    if operation == "ALTER":

        return {
            "impact_type": "SCHEMA_MODIFICATION",
            "risk_level": "CRITICAL"
        }

    # ========================================================
    # TRUNCATE
    # ========================================================

    if operation == "TRUNCATE":

        return {
            "impact_type": "DATA_DELETION",
            "risk_level": "CRITICAL"
        }

    # ========================================================
    # UNKNOWN
    # ========================================================

    return {
        "impact_type": "UNKNOWN",
        "risk_level": "HIGH"
    }


# ============================================================
# Main Guardian Check
# ============================================================

def guardian_check(
    user_request,
    sql,
    known_intent=None,
    connection=None,
    table_name="employees"
):
    """
    Main GuardianAgent safety gateway.

    Existing usage:

        guardian_check(
            request,
            sql,
            known_intent=intent
        )

    continues to use:

        company.db
        employees

    DBBench can provide:

        connection=<DB connection>
        table_name=<DBBench table>

    so Guardian does not assume the company.db schema.
    """

    # ========================================================
    # 1. Intent Analysis
    # ========================================================

    if known_intent is not None:

        intent = known_intent

    else:

        intent = analyze_intent(
            user_request
        )

    # ========================================================
    # 2. SQL Analysis
    # ========================================================

    sql_info = analyze_sql(
        sql
    )

    # ========================================================
    # 3. Scope Analysis
    # ========================================================

    scope = analyze_scope_safely(
        sql,
        connection=connection,
        table_name=table_name
    )

    # ========================================================
    # 4. Database Impact
    # ========================================================

    impact = analyze_impact(
        sql,
        scope
    )

    # ========================================================
    # 5. Intent-SQL Consistency
    # ========================================================

    intent_sql_result = check_intent_sql(
        intent,
        sql_info,
        scope
    )

    # ========================================================
    # 6. Risk Engine
    # ========================================================

    risk = calculate_risk(
        intent,
        sql_info,
        scope,
        impact,
        intent_sql_result
    )

    # ========================================================
    # Final Guardian Result
    # ========================================================

    return {
        "intent": intent,

        "sql_info": sql_info,

        "scope": scope,

        "impact": impact,

        "intent_sql": intent_sql_result,

        "risk": risk
    }


# ============================================================
# Original Database Execution
# ============================================================

def execute_query(sql):

    connection = sqlite3.connect(
        "company.db"
    )

    cursor = connection.cursor()

    cursor.execute(
        sql
    )

    if sql.strip().upper().startswith(
        "SELECT"
    ):

        result = cursor.fetchall()

    else:

        connection.commit()

        result = []

    connection.close()

    return result


# ============================================================
# Execute With Guardian
# ============================================================

def execute_with_guardian(
    user_request,
    sql
):
    """
    Original interactive GuardianAgent execution flow.

    ALLOW:
        execute automatically.

    CONFIRM:
        ask the user.

    BLOCK:
        do not execute.
    """

    result = guardian_check(
        user_request,
        sql
    )

    decision = (
        result["risk"]["decision"]
    )

    print(
        "\nGUARDIAN DECISION:",
        decision
    )

    # ========================================================
    # BLOCK
    # ========================================================

    if decision == "BLOCK":

        print(
            "SQL BLOCKED."
        )

        return None

    # ========================================================
    # CONFIRM
    # ========================================================

    if decision == "CONFIRM":

        print(
            "SQL requires user confirmation."
        )

        answer = input(
            "Do you want to execute this SQL? (yes/no): "
        )

        if answer.lower() != "yes":

            print(
                "SQL execution cancelled."
            )

            return None

    # ========================================================
    # ALLOW
    # ========================================================

    if decision == "ALLOW":

        print(
            "SQL automatically allowed."
        )

    # ========================================================
    # Execute
    # ========================================================

    print(
        "Executing SQL..."
    )

    return execute_query(
        sql
    )


# ============================================================
# Main Demo
# ============================================================

if __name__ == "__main__":

    user_request = (
        "Change Arun's salary to 70000."
    )

    sql = generate_sql(
        user_request
    )

    print(
        "\nUSER REQUEST:"
    )

    print(
        user_request
    )

    print(
        "\nGENERATED SQL:"
    )

    print(
        sql
    )

    result = execute_with_guardian(
        user_request,
        sql
    )

    if result is not None:

        print(
            "\nRESULT:"
        )

        for row in result:

            print(
                row
            )