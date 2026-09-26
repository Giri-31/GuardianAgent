"""
guardian.py

GuardianAgent: Consequence-Aware Safety Verification
for LLM-Generated Database Actions.

Pipeline
--------
User Request
    |
    v
Intent Analysis
    |
    v
Generated SQL
    |
    v
SQL Analysis
    |
    +----> Scope Analysis
    |
    +----> Impact Analysis
    |
    +----> Intent-SQL Consistency
    |
    v
Risk Engine
    |
    +----> ALLOW
    +----> CONFIRM
    +----> BLOCK
    |
    v
Database Execution

Important execution policy
--------------------------
ALLOW   -> execute automatically
CONFIRM -> require explicit user confirmation
BLOCK   -> never execute

The safety gateway is schema-independent when supplied with an
external database connection and table name.

The original company.db / employees demo is retained only for
backward compatibility and demonstration.
"""

import os
import sqlite3

from sql_analyzer import analyze_sql
from intent_analyzer import analyze_intent
from intent_sql_checker import check_intent_sql
from risk_engine import calculate_risk
from scope_analyzer import analyze_scope


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATABASE = os.path.join(BASE_DIR, "company.db")
DEFAULT_TABLE = "employees"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# ============================================================
# GEMINI CLIENT
# ============================================================

def _get_gemini_client():
    """
    Create the Gemini client only when SQL generation is requested.

    This prevents importing guardian.py from requiring a valid
    Gemini API key.

    The safety gateway itself does not require Gemini.
    """

    try:

        from google import genai

    except ImportError as exc:

        raise RuntimeError(
            "google-genai is required for SQL generation."
        ) from exc

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "GEMINI_API_KEY is not set."
        )

    return genai.Client(
        api_key=api_key
    )


def _safe_text(response):
    """
    Safely extract text from a Gemini response.

    Accessing response.text raises an exception when the model
    returns no output (e.g. safety filter block).  This helper
    extracts text via the candidates list first so that callers
    can handle empty responses without crashing.
    """

    try:
        text = response.text
        if text:
            return text.strip()
    except Exception:
        pass

    try:
        for candidate in (response.candidates or []):
            for part in (candidate.content.parts or []):
                t = getattr(part, "text", None)
                if t:
                    return t.strip()
    except Exception:
        pass

    return ""


# ============================================================
# SQL GENERATION
# ============================================================

def generate_sql(user_request):
    """
    Generate SQL for the original GuardianAgent demo.

    This function is intentionally separate from the safety
    verification pipeline.

    The demo uses:

        company.db
        employees

    External database integrations should supply their own
    SQL-generation mechanism and pass the generated SQL into
    guardian_check().
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

    client = _get_gemini_client()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    text = _safe_text(response)

    if not text:

        raise RuntimeError(
            "Gemini returned an empty SQL response. "
            "The request may have been blocked by safety filters."
        )

    return text


# ============================================================
# SCOPE ANALYSIS
# ============================================================

def analyze_scope_safely(
    sql,
    connection=None,
    table_name=DEFAULT_TABLE
):
    """
    Estimate the number of rows affected/read by SQL.

    This function delegates to the reusable scope_analyzer
    module.

    Scope categories:

        ZERO_ROWS
        ONE_ROW
        MULTIPLE_ROWS
        ALL_ROWS
        UNKNOWN

    Safety property
    ---------------
    The SQL statement itself is never executed as a mutation.

    For filtered statements, scope_analyzer may execute a
    read-only COUNT(*) query against the supplied database.

    Parameters
    ----------
    sql:
        SQL statement to analyze.

    connection:
        Optional SQLite connection.

        If supplied, that database is used.

        If omitted, company.db is used for backward-compatible
        GuardianAgent experiments.

    table_name:
        Table against which row scope is evaluated.

        Defaults to employees only for the original demo.
    """

    # If no connection was supplied, try to open the default database
    # so that filtered queries get proper row counts instead of UNKNOWN.
    if connection is None and os.path.isfile(DEFAULT_DATABASE):
        _conn = None
        try:
            _conn = sqlite3.connect(DEFAULT_DATABASE)
            # Auto-infer table name from SQL when using defaults
            _table = table_name
            if _table == DEFAULT_TABLE:
                _sql_info = analyze_sql(sql)
                _detected = _sql_info.get("table")
                if _detected:
                    _table = _detected
            return analyze_scope(
                sql,
                connection=_conn,
                table_name=_table
            )
        except Exception:
            pass
        finally:
            if _conn is not None:
                try:
                    _conn.close()
                except Exception:
                    pass

    return analyze_scope(
        sql,
        connection=connection,
        table_name=table_name
    )


# ============================================================
# DATABASE IMPACT ANALYSIS
# ============================================================

def analyze_impact(
    sql,
    scope
):
    """
    Estimate potential database impact.

    This function is schema-independent.

    It does NOT:

        - know table names
        - know column names
        - execute SQL
        - modify the database

    It uses only:

        SQL operation
        observed scope
    """

    sql_info = analyze_sql(
        sql
    )

    operation = str(
        sql_info.get(
            "operation",
            "UNKNOWN"
        )
    ).upper()

    scope = str(
        scope
    ).upper()

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

            risk_level = "HIGH"

        elif scope == "ONE_ROW":

            risk_level = "MEDIUM"

        else:

            risk_level = "MEDIUM"

        return {
            "impact_type": "DATA_CREATION",
            "risk_level": risk_level
        }

    # ========================================================
    # UPDATE
    # ========================================================

    if operation == "UPDATE":

        if scope == "ZERO_ROWS":

            risk_level = "LOW"

        elif scope == "ONE_ROW":

            risk_level = "MEDIUM"

        elif scope == "MULTIPLE_ROWS":

            risk_level = "HIGH"

        elif scope == "ALL_ROWS":

            risk_level = "CRITICAL"

        else:

            risk_level = "HIGH"

        return {
            "impact_type": "DATA_MODIFICATION",
            "risk_level": risk_level
        }

    # ========================================================
    # DELETE
    # ========================================================

    if operation == "DELETE":

        if scope == "ZERO_ROWS":

            risk_level = "LOW"

        elif scope == "ONE_ROW":

            risk_level = "HIGH"

        else:

            risk_level = "CRITICAL"

        return {
            "impact_type": "DATA_DELETION",
            "risk_level": risk_level
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
# MAIN GUARDIAN CHECK
# ============================================================

def guardian_check(
    user_request,
    sql,
    known_intent=None,
    connection=None,
    table_name=DEFAULT_TABLE
):
    """
    Run the complete GuardianAgent safety pipeline.

    Parameters
    ----------
    user_request:
        Original natural-language user request.

    sql:
        SQL generated by an upstream SQL agent.

    known_intent:
        Optional precomputed intent.

        If provided, GuardianAgent uses it directly.
        Otherwise analyze_intent() is called.

    connection:
        Optional database connection.

        Used for scope analysis.

    table_name:
        Table used for scope analysis.

        The default exists only for the original company.db
        demonstration.

    Returns
    -------
    dict

        {
            "intent": ...,
            "sql_info": ...,
            "scope": ...,
            "impact": ...,
            "intent_sql": ...,
            "risk": ...
        }

    Important
    ---------
    This function ONLY analyzes the proposed SQL.

    It does not execute the SQL.
    """

    # ========================================================
    # 1. INTENT ANALYSIS
    # ========================================================

    if known_intent is not None:

        intent = known_intent

    else:

        intent = analyze_intent(
            user_request
        )

    # ========================================================
    # 2. SQL ANALYSIS
    # ========================================================

    sql_info = analyze_sql(
        sql
    )

    # ========================================================
    # 3. SCOPE ANALYSIS
    # ========================================================

    scope = analyze_scope_safely(
        sql,
        connection=connection,
        table_name=table_name
    )

    # ========================================================
    # 4. IMPACT ANALYSIS
    # ========================================================

    impact = analyze_impact(
        sql,
        scope
    )

    # ========================================================
    # 5. INTENT-SQL CONSISTENCY
    # ========================================================

    intent_sql_result = check_intent_sql(
        intent,
        sql,
        connection=connection,
    )

    # ========================================================
    # 6. RISK ENGINE
    # ========================================================

    risk = calculate_risk(
        intent=intent,
        sql_info=sql_info,
        scope=scope,
        impact=impact,
        intent_sql_result=intent_sql_result
    )

    # ========================================================
    # 7. COMPLETE RESULT
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
# DATABASE EXECUTION
# ============================================================

def execute_query(
    sql,
    connection=None
):
    """
    Execute SQL after Guardian has permitted execution.

    Parameters
    ----------
    sql:
        SQL statement.

    connection:
        Optional SQLite connection.

        If omitted, company.db is opened for backward-compatible
        demo execution.

    Important
    ---------
    This function itself does not perform Guardian verification.

    Call execute_with_guardian() when the SQL originates from an
    untrusted or LLM-generated source.
    """

    owns_connection = (
        connection is None
    )

    if owns_connection:

        connection = sqlite3.connect(
            DEFAULT_DATABASE
        )

    try:

        cursor = connection.cursor()

        cursor.execute(
            sql
        )

        operation = analyze_sql(
            sql
        ).get(
            "operation",
            "UNKNOWN"
        )

        if operation == "SELECT":

            result = cursor.fetchall()

        else:

            connection.commit()

            result = []

        return result

    finally:

        if owns_connection:

            connection.close()


# ============================================================
# EXECUTION GATE
# ============================================================

def execute_with_guardian(
    user_request,
    sql,
    known_intent=None,
    connection=None,
    table_name=DEFAULT_TABLE
):
    """
    Analyze SQL with GuardianAgent and enforce the resulting
    execution decision.

    Execution policy
    ----------------
    ALLOW:
        execute automatically.

    CONFIRM:
        request explicit user confirmation.

    BLOCK:
        do not execute.

    This function is the execution boundary between the
    safety gateway and the database.
    """

    result = guardian_check(
        user_request=user_request,
        sql=sql,
        known_intent=known_intent,
        connection=connection,
        table_name=table_name
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

        return {
            "executed": False,
            "decision": "BLOCK",
            "result": result,
            "data": None
        }

    # ========================================================
    # CONFIRM
    # ========================================================

    if decision == "CONFIRM":

        print(
            "SQL requires user confirmation."
        )

        answer = input(
            "Do you want to execute this SQL? (yes/no): "
        ).strip().lower()

        if answer != "yes":

            print(
                "SQL execution cancelled."
            )

            return {
                "executed": False,
                "decision": "CONFIRM",
                "result": result,
                "data": None
            }

    # ========================================================
    # ALLOW
    # ========================================================

    elif decision == "ALLOW":

        print(
            "SQL automatically allowed."
        )

    # ========================================================
    # UNKNOWN DECISION
    # ========================================================

    else:

        print(
            "Unknown Guardian decision. "
            "SQL execution cancelled."
        )

        return {
            "executed": False,
            "decision": decision,
            "result": result,
            "data": None
        }

    # ========================================================
    # EXECUTION
    # ========================================================

    print(
        "Executing SQL..."
    )

    try:

        data = execute_query(
            sql,
            connection=connection
        )

        return {
            "executed": True,
            "decision": decision,
            "result": result,
            "data": data
        }

    except Exception as exc:

        return {
            "executed": False,
            "decision": decision,
            "result": result,
            "data": None,
            "execution_error": str(exc)
        }


# ============================================================
# DISPLAY HELPER
# ============================================================

def print_guardian_result(result):
    """
    Print a structured Guardian result for debugging and
    experiments.
    """

    print()
    print("=" * 70)
    print("GUARDIANAGENT ANALYSIS")
    print("=" * 70)

    print()
    print("INTENT")
    print("-" * 70)
    print(
        result["intent"]
    )

    print()
    print("SQL ANALYSIS")
    print("-" * 70)
    print(
        result["sql_info"]
    )

    print()
    print("SCOPE")
    print("-" * 70)
    print(
        result["scope"]
    )

    print()
    print("IMPACT")
    print("-" * 70)
    print(
        result["impact"]
    )

    print()
    print("INTENT-SQL CONSISTENCY")
    print("-" * 70)
    print(
        result["intent_sql"]
    )

    print()
    print("RISK")
    print("-" * 70)
    print(
        result["risk"]
    )

    print()
    print("=" * 70)


# ============================================================
# MAIN DEMO
# ============================================================

if __name__ == "__main__":

    user_request = (
        "Change Arun's salary to 70000."
    )

    print(
        "\nUSER REQUEST:"
    )

    print(
        user_request
    )

    # --------------------------------------------------------
    # Generate SQL using the original demo LLM pipeline.
    # --------------------------------------------------------

    sql = generate_sql(
        user_request
    )

    print(
        "\nGENERATED SQL:"
    )

    print(
        sql
    )

    # --------------------------------------------------------
    # Analyze before execution.
    # --------------------------------------------------------

    analysis = guardian_check(
        user_request=user_request,
        sql=sql
    )

    print_guardian_result(
        analysis
    )

    # --------------------------------------------------------
    # Enforce Guardian decision.
    # --------------------------------------------------------

    execution = execute_with_guardian(
        user_request=user_request,
        sql=sql
    )

    # --------------------------------------------------------
    # Display returned data.
    # --------------------------------------------------------

    if execution["executed"]:

        print(
            "\nRESULT:"
        )

        for row in execution["data"]:

            print(
                row
            )