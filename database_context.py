"""
Database context and impact analysis for GuardianAgent.

This module provides database-aware context without assuming a
specific database, table, or column structure.

The module does not execute user-requested mutation SQL.
"""

from sql_analyzer import analyze_sql
from scope_analyzer import analyze_scope


# ============================================================
# Impact Analysis
# ============================================================

def analyze_database_impact(
    sql,
    connection=None,
    table_name=None,
):
    """
    Analyze the potential database impact of a SQL statement.

    Parameters
    ----------
    sql:
        SQL statement to analyze.

    connection:
        Optional database connection used for scope analysis.

    table_name:
        Optional table name.

        If omitted, the table is obtained from sql_analyzer.

    Returns
    -------
    dict

        {
            "operation": ...,
            "scope": ...,
            "impact_type": ...,
            "risk_level": ...
        }

    This function NEVER executes the supplied mutation SQL.
    """

    # --------------------------------------------------------
    # SQL analysis
    # --------------------------------------------------------

    sql_info = analyze_sql(
        sql
    )

    operation = sql_info.get(
        "operation",
        "UNKNOWN",
    )

    # --------------------------------------------------------
    # Resolve table
    # --------------------------------------------------------

    if table_name is None:

        table_name = sql_info.get(
            "table"
        )

    # --------------------------------------------------------
    # Database-aware scope
    # --------------------------------------------------------

    scope = analyze_scope(
        sql=sql,
        connection=connection,
        table_name=table_name,
    )

    # --------------------------------------------------------
    # SELECT
    # --------------------------------------------------------

    if operation == "SELECT":

        return {
            "operation": operation,
            "scope": scope,
            "impact_type": "READ",
            "risk_level": "LOW",
        }

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    if operation == "INSERT":

        if scope == "MULTIPLE_ROWS":

            risk_level = "HIGH"

        else:

            risk_level = "MEDIUM"

        return {
            "operation": operation,
            "scope": scope,
            "impact_type": "DATA_CREATION",
            "risk_level": risk_level,
        }

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

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
            "operation": operation,
            "scope": scope,
            "impact_type": "DATA_MODIFICATION",
            "risk_level": risk_level,
        }

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    if operation == "DELETE":

        if scope == "ZERO_ROWS":

            risk_level = "LOW"

        elif scope == "ONE_ROW":

            risk_level = "HIGH"

        else:

            risk_level = "CRITICAL"

        return {
            "operation": operation,
            "scope": scope,
            "impact_type": "DATA_DELETION",
            "risk_level": risk_level,
        }

    # --------------------------------------------------------
    # DROP
    # --------------------------------------------------------

    if operation == "DROP":

        return {
            "operation": operation,
            "scope": scope,
            "impact_type": "SCHEMA_DESTRUCTION",
            "risk_level": "CRITICAL",
        }

    # --------------------------------------------------------
    # ALTER
    # --------------------------------------------------------

    if operation == "ALTER":

        return {
            "operation": operation,
            "scope": scope,
            "impact_type": "SCHEMA_MODIFICATION",
            "risk_level": "CRITICAL",
        }

    # --------------------------------------------------------
    # TRUNCATE
    # --------------------------------------------------------

    if operation == "TRUNCATE":

        return {
            "operation": operation,
            "scope": scope,
            "impact_type": "DATA_DELETION",
            "risk_level": "CRITICAL",
        }

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    return {
        "operation": operation,
        "scope": scope,
        "impact_type": "UNKNOWN",
        "risk_level": "HIGH",
    }


# ============================================================
# Simple Impact-Only Wrapper
# ============================================================

def get_impact_level(
    sql,
    connection=None,
    table_name=None,
):
    """
    Return only the calculated impact risk level.

    Example:

        HIGH
        CRITICAL
        MEDIUM
        LOW
    """

    result = analyze_database_impact(
        sql=sql,
        connection=connection,
        table_name=table_name,
    )

    return result[
        "risk_level"
    ]


# ============================================================
# Standalone Tests
# ============================================================

if __name__ == "__main__":

    import sqlite3

    print("=" * 70)
    print("DATABASE CONTEXT TESTS")
    print("=" * 70)

    # --------------------------------------------------------
    # Temporary database.
    # --------------------------------------------------------

    connection = sqlite3.connect(
        ":memory:"
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE employees (
            id INTEGER,
            name TEXT,
            department TEXT,
            status TEXT,
            salary INTEGER
        )
        """
    )

    cursor.executemany(
        """
        INSERT INTO employees
        (id, name, department, status, salary)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "Arun",
                "IT",
                "active",
                50000,
            ),
            (
                2,
                "Meera",
                "HR",
                "active",
                60000,
            ),
            (
                3,
                "Rahul",
                "HR",
                "inactive",
                55000,
            ),
        ],
    )

    connection.commit()

    # --------------------------------------------------------
    # Test cases.
    # --------------------------------------------------------

    tests = [

        (
            "SELECT",
            """
            SELECT *
            FROM employees
            WHERE department = 'HR';
            """,
        ),

        (
            "Single-row UPDATE",
            """
            UPDATE employees
            SET salary = 70000
            WHERE name = 'Arun';
            """,
        ),

        (
            "Multi-row UPDATE",
            """
            UPDATE employees
            SET salary = salary + 5000
            WHERE department = 'HR';
            """,
        ),

        (
            "All-row UPDATE",
            """
            UPDATE employees
            SET salary = 70000;
            """,
        ),

        (
            "Single-row DELETE",
            """
            DELETE FROM employees
            WHERE name = 'Arun';
            """,
        ),

        (
            "All-row DELETE",
            """
            DELETE FROM employees;
            """,
        ),

        (
            "DROP",
            """
            DROP TABLE employees;
            """,
        ),

        (
            "ALTER",
            """
            ALTER TABLE employees
            ADD COLUMN age INTEGER;
            """,
        ),
    ]

    for name, sql in tests:

        print("\n" + "-" * 70)
        print(name)
        print("-" * 70)

        print(
            "SQL:",
            sql.strip(),
        )

        result = analyze_database_impact(
            sql=sql,
            connection=connection,
            table_name="employees",
        )

        print(
            "RESULT:",
            result,
        )

    # --------------------------------------------------------
    # Safety verification.
    #
    # None of the UPDATE/DELETE/DROP/ALTER statements above
    # should have actually modified the database.
    # --------------------------------------------------------

    cursor.execute(
        "SELECT COUNT(*) FROM employees"
    )

    row_count = cursor.fetchone()[0]

    print("\n" + "=" * 70)
    print("SAFETY CHECK")
    print("=" * 70)

    print(
        "Rows remaining:",
        row_count,
    )

    if row_count == 3:

        print(
            "PASS: Impact analysis did not execute mutations."
        )

    else:

        print(
            "FAIL: Database state changed."
        )

    connection.close()