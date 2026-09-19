"""
Database-aware SQL scope analysis for GuardianAgent.

This module estimates how many rows a SQL statement targets without
executing the requested INSERT / UPDATE / DELETE / DDL operation.

Scope categories:

    ZERO_ROWS
    ONE_ROW
    MULTIPLE_ROWS
    ALL_ROWS
    UNKNOWN

The module is schema-independent.

It does NOT assume:

    company.db
    employees
    id
    name
    salary
    department
    status
"""

import re
import sqlite3

from sql_analyzer import (
    analyze_sql,
    clean_sql,
)


# ============================================================
# Scope Constants
# ============================================================

ZERO_ROWS = "ZERO_ROWS"
ONE_ROW = "ONE_ROW"
MULTIPLE_ROWS = "MULTIPLE_ROWS"
ALL_ROWS = "ALL_ROWS"
UNKNOWN = "UNKNOWN"


# ============================================================
# Identifier Utilities
# ============================================================

def quote_identifier(name):
    """
    Safely quote an SQLite identifier.

    Example:

        employees
        ->
        "employees"

        Some Table
        ->
        "Some Table"
    """

    if name is None:
        raise ValueError(
            "table_name cannot be None"
        )

    return (
        '"'
        + str(name).replace(
            '"',
            '""'
        )
        + '"'
    )


# ============================================================
# WHERE Extraction
# ============================================================

def extract_where_condition(sql):
    """
    Extract the WHERE condition from SQL.

    This delegates SQL parsing to sql_analyzer.py so that there
    is only one implementation of WHERE extraction.

    Returns:
        condition string
        or None
    """

    sql_info = analyze_sql(
        sql
    )

    return sql_info.get(
        "where"
    )


# ============================================================
# INSERT Scope
# ============================================================

def analyze_insert_scope(sql):
    """
    Estimate INSERT scope from the VALUES clause.

    Examples:

        INSERT INTO t VALUES (1);
        -> ONE_ROW

        INSERT INTO t VALUES (1), (2);
        -> MULTIPLE_ROWS

    INSERT ... SELECT is not safely estimated here and therefore
    returns UNKNOWN.
    """

    if not sql:
        return UNKNOWN

    sql_clean = clean_sql(
        sql
    )

    sql_upper = sql_clean.upper()

    # --------------------------------------------------------
    # INSERT ... SELECT
    # --------------------------------------------------------

    if re.search(
        r"\bINSERT\s+INTO\b.*\bSELECT\b",
        sql_upper,
        flags=re.IGNORECASE |
        re.DOTALL,
    ):

        return UNKNOWN

    # --------------------------------------------------------
    # Find VALUES
    # --------------------------------------------------------

    values_match = re.search(
        r"\bVALUES\b",
        sql_clean,
        flags=re.IGNORECASE,
    )

    if not values_match:
        return UNKNOWN

    start = values_match.end()

    values_part = sql_clean[
        start:
    ]

    # Remove trailing semicolon.
    values_part = values_part.rstrip(
        ";"
    ).strip()

    if not values_part:
        return UNKNOWN

    # --------------------------------------------------------
    # Count top-level tuples.
    #
    # We cannot simply use:
    #
    #     re.findall(r"\([^()]*\)")
    #
    # because values can contain nested expressions.
    # --------------------------------------------------------

    tuple_count = 0

    depth = 0
    in_single_quote = False
    in_double_quote = False
    in_backtick = False

    i = 0

    while i < len(values_part):

        char = values_part[i]

        # ----------------------------------------------------
        # Single quoted strings
        # ----------------------------------------------------

        if (
            char == "'"
            and not in_double_quote
            and not in_backtick
        ):

            if (
                in_single_quote
                and i + 1 < len(values_part)
                and values_part[i + 1] == "'"
            ):

                i += 2
                continue

            in_single_quote = (
                not in_single_quote
            )

            i += 1
            continue

        # ----------------------------------------------------
        # Double quoted strings / identifiers
        # ----------------------------------------------------

        if (
            char == '"'
            and not in_single_quote
            and not in_backtick
        ):

            in_double_quote = (
                not in_double_quote
            )

            i += 1
            continue

        # ----------------------------------------------------
        # Backtick identifiers
        # ----------------------------------------------------

        if (
            char == "`"
            and not in_single_quote
            and not in_double_quote
        ):

            in_backtick = (
                not in_backtick
            )

            i += 1
            continue

        # ----------------------------------------------------
        # Parentheses
        # ----------------------------------------------------

        if (
            char == "("
            and not in_single_quote
            and not in_double_quote
            and not in_backtick
        ):

            if depth == 0:
                tuple_count += 1

            depth += 1

        elif (
            char == ")"
            and not in_single_quote
            and not in_double_quote
            and not in_backtick
        ):

            if depth > 0:
                depth -= 1

        i += 1

    if tuple_count == 1:
        return ONE_ROW

    if tuple_count > 1:
        return MULTIPLE_ROWS

    return UNKNOWN


# ============================================================
# Count Rows Matching WHERE
# ============================================================

def _strip_alias_prefix(where_condition):
    """
    Remove table-alias dot-prefixes from a WHERE clause.

    Example::

        e.status = 'active' AND e.salary > 50000
        ->
        status = 'active' AND salary > 50000

    This is needed because count_matching_rows builds its own
    ``FROM table WHERE ...`` query and column references like
    ``e.salary`` are not valid without the alias.
    """
    # Replace alias.column patterns (simple identifier . identifier)
    # that appear as whole tokens (preceded by space, operator, '(' or
    # start-of-string and followed by space, operator, ')' or end).
    return re.sub(
        r'(?<![.\w])([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)',
        r'\2',
        where_condition,
    )


def count_matching_rows(
    connection,
    table_name,
    where_condition,
):
    """
    Count rows matching a WHERE predicate.

    IMPORTANT:

    This executes only a SELECT COUNT(*) query.

    It does NOT execute the user's requested mutation.

    Therefore:

        UPDATE ...
        DELETE ...

    are never executed here.

    Parameters:

        connection:
            Existing database connection.

        table_name:
            Table on which the SQL operates.

        where_condition:
            Extracted WHERE expression.
    """

    if connection is None:
        return None

    if not table_name:
        return None

    if not where_condition:
        return None

    # Strip alias dot-prefixes (e.g. e.salary → salary) so the
    # plain FROM table WHERE ... COUNT query stays valid.
    clean_where = _strip_alias_prefix(where_condition)

    quoted_table = quote_identifier(
        table_name
    )

    count_query = (
        "SELECT COUNT(*) "
        "FROM "
        + quoted_table
        + " WHERE "
        + clean_where
    )

    try:

        cursor = connection.cursor()

        cursor.execute(
            count_query
        )

        row = cursor.fetchone()

        if row is None:
            return None

        return int(
            row[0]
        )

    except Exception:

        return None


# ============================================================
# Convert Row Count → Scope
# ============================================================

def classify_row_count(row_count):
    """
    Convert a row count into Guardian scope categories.
    """

    if row_count is None:
        return UNKNOWN

    if row_count == 0:
        return ZERO_ROWS

    if row_count == 1:
        return ONE_ROW

    return MULTIPLE_ROWS


# ============================================================
# Database-Aware Scope
# ============================================================

def analyze_scope(
    sql,
    connection=None,
    table_name=None,
):
    """
    Analyze the database-aware scope of SQL.

    Parameters
    ----------
    sql:
        SQL statement to analyze.

    connection:
        Existing SQLite connection.

        If None, this function cannot determine database-aware
        scope and returns UNKNOWN unless the statement itself
        provides enough information.

    table_name:
        Optional explicit table name.

        If omitted, the table is extracted from sql_analyzer.py.

    Returns
    -------
    str

        ZERO_ROWS
        ONE_ROW
        MULTIPLE_ROWS
        ALL_ROWS
        UNKNOWN

    Safety property
    ---------------
    The generated SQL operation is NEVER executed.

    Only SELECT COUNT(*) is used for predicate cardinality.
    """

    if not sql:
        return UNKNOWN

    sql_clean = clean_sql(
        sql
    )

    if not sql_clean:
        return UNKNOWN

    # ========================================================
    # SQL analysis
    # ========================================================

    sql_info = analyze_sql(
        sql_clean
    )

    operation = sql_info.get(
        "operation",
        "UNKNOWN",
    )

    # ========================================================
    # Resolve table
    # ========================================================

    if table_name is None:

        table_name = sql_info.get(
            "table"
        )

    # ========================================================
    # INSERT
    # ========================================================

    if operation == "INSERT":

        return analyze_insert_scope(
            sql_clean
        )

    # ========================================================
    # Unsupported operations
    # ========================================================

    if operation in {
        "DROP",
        "ALTER",
        "TRUNCATE",
        "UNKNOWN",
    }:

        return UNKNOWN

    # ========================================================
    # SELECT / UPDATE / DELETE without WHERE
    # ========================================================

    where_condition = (
        sql_info.get(
            "where"
        )
    )

    if where_condition is None:

        if operation in {
            "SELECT",
            "UPDATE",
            "DELETE",
        }:

            return ALL_ROWS

        return UNKNOWN

    # ========================================================
    # No DB connection
    # ========================================================

    if connection is None:

        # We know that the query is filtered,
        # but cannot safely determine how many rows
        # it targets without database context.

        return UNKNOWN

    # ========================================================
    # No table
    # ========================================================

    if not table_name:

        return UNKNOWN

    # ========================================================
    # Count matching rows
    # ========================================================

    row_count = count_matching_rows(
        connection=connection,
        table_name=table_name,
        where_condition=where_condition,
    )

    return classify_row_count(
        row_count
    )


# ============================================================
# Convenience Wrapper
# ============================================================

def analyze_scope_with_database(
    sql,
    database_path,
    table_name=None,
):
    """
    Convenience function for standalone use.

    This function opens a database connection, performs the
    read-only scope analysis, and closes the connection.

    Guardian itself should preferably pass an existing connection
    to avoid repeatedly opening databases.
    """

    if not database_path:
        return UNKNOWN

    connection = None

    try:

        connection = sqlite3.connect(
            database_path
        )

        return analyze_scope(
            sql=sql,
            connection=connection,
            table_name=table_name,
        )

    except Exception:

        return UNKNOWN

    finally:

        if connection is not None:

            try:
                connection.close()

            except Exception:
                pass


# ============================================================
# Standalone Tests
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("SCOPE ANALYZER TESTS")
    print("=" * 70)

    # --------------------------------------------------------
    # Create a temporary in-memory database.
    #
    # This test database is intentionally created here only
    # for testing. The scope analyzer itself does not assume
    # this schema.
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
                "IT",
                "inactive",
                55000,
            ),
            (
                4,
                "Anu",
                "Finance",
                "active",
                65000,
            ),
        ],
    )

    connection.commit()

    test_queries = [

        (
            "Single row",
            """
            UPDATE employees
            SET salary = 70000
            WHERE name = 'Arun';
            """,
        ),

        (
            "Multiple rows",
            """
            UPDATE employees
            SET salary = 70000
            WHERE department = 'IT';
            """,
        ),

        (
            "Zero rows",
            """
            UPDATE employees
            SET salary = 70000
            WHERE name = 'Nobody';
            """,
        ),

        (
            "All rows",
            """
            UPDATE employees
            SET salary = 70000;
            """,
        ),

        (
            "Single-row delete",
            """
            DELETE FROM employees
            WHERE name = 'Arun';
            """,
        ),

        (
            "Multiple-row delete",
            """
            DELETE FROM employees
            WHERE department = 'IT';
            """,
        ),

        (
            "Select filtered",
            """
            SELECT *
            FROM employees
            WHERE department = 'IT';
            """,
        ),

        (
            "Select all",
            """
            SELECT *
            FROM employees;
            """,
        ),

        (
            "Insert one",
            """
            INSERT INTO employees
            (id, name, department, status, salary)
            VALUES (5, 'Test', 'IT', 'active', 50000);
            """,
        ),

        (
            "Insert multiple",
            """
            INSERT INTO employees
            (id, name, department, status, salary)
            VALUES
                (5, 'Test1', 'IT', 'active', 50000),
                (6, 'Test2', 'HR', 'active', 60000);
            """,
        ),

        (
            "Drop table",
            """
            DROP TABLE employees;
            """,
        ),
    ]

    for name, query in test_queries:

        result = analyze_scope(
            sql=query,
            connection=connection,
            table_name="employees",
        )

        print("\n" + "-" * 70)
        print(name)
        print("-" * 70)
        print("SQL:")
        print(query.strip())
        print("\nSCOPE:")
        print(result)

    # --------------------------------------------------------
    # Verify that mutation queries did NOT execute.
    # --------------------------------------------------------

    cursor.execute(
        "SELECT COUNT(*) FROM employees"
    )

    remaining_rows = (
        cursor.fetchone()[0]
    )

    print("\n" + "=" * 70)
    print("SAFETY CHECK")
    print("=" * 70)

    print(
        "Rows remaining:",
        remaining_rows,
    )

    if remaining_rows == 4:

        print(
            "PASS: No mutation query was executed."
        )

    else:

        print(
            "FAIL: Database state changed."
        )

    connection.close()