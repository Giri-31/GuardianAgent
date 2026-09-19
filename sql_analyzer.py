import re


SUPPORTED_OPERATIONS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
}


def clean_sql(sql):
    """
    Normalize SQL text without changing its meaning.

    Removes:
    - leading/trailing whitespace
    - markdown SQL fences
    """

    if sql is None:
        return ""

    sql = str(sql).strip()

    # Remove markdown code fences.
    sql = re.sub(
        r"^```(?:sql)?\s*",
        "",
        sql,
        flags=re.IGNORECASE,
    )

    sql = re.sub(
        r"\s*```$",
        "",
        sql,
        flags=re.IGNORECASE,
    )

    return sql.strip()


def _strip_leading_comments(sql):
    """
    Remove SQL comments appearing before the statement.
    """

    sql = re.sub(
        r"^\s*--.*?(?:\r?\n|$)",
        "",
        sql,
    )

    sql = re.sub(
        r"^\s*/\*.*?\*/\s*",
        "",
        sql,
        flags=re.DOTALL,
    )

    return sql.strip()


def detect_operation(sql):
    """
    Detect the primary SQL operation.

    Supported:
        SELECT
        INSERT
        UPDATE
        DELETE
        DROP
        ALTER
        TRUNCATE

    For WITH queries, the first meaningful DML operation
    following the CTE is detected.

    Returns:
        operation string
        or UNKNOWN
    """

    sql = clean_sql(sql)
    sql = _strip_leading_comments(sql)

    if not sql:
        return "UNKNOWN"

    # Remove a leading WITH clause when possible and look
    # for the actual DML operation.
    upper_sql = sql.upper()

    # Direct statements.
    for operation in SUPPORTED_OPERATIONS:

        if re.match(
            rf"^\s*{operation}\b",
            upper_sql,
        ):
            return operation

    # CTE / WITH statement.
    if re.match(
        r"^\s*WITH\b",
        upper_sql,
    ):

        # Look for the first actual DML operation after
        # the CTE definitions.
        match = re.search(
            r"\b(SELECT|INSERT|UPDATE|DELETE)\b",
            upper_sql,
        )

        if match:
            return match.group(1)

    return "UNKNOWN"


def _extract_identifier(pattern, sql):
    """
    Extract an SQL identifier supporting:

        table
        "table name"
        `table name`
        [table name]
    """

    match = re.search(
        pattern,
        sql,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    identifier = match.group(1).strip()

    if (
        len(identifier) >= 2
        and identifier[0] == identifier[-1]
        and identifier[0] in {
            '"',
            "`",
            "[",
        }
    ):

        if identifier[0] == "[":
            identifier = identifier[1:-1]
        else:
            identifier = identifier[1:-1]

    return identifier


def extract_table(sql, operation):
    """
    Extract the primary table associated with the SQL operation.

    Supports quoted identifiers and table names containing spaces.
    """

    if not sql:
        return None

    patterns = {
        "SELECT": [
            r"\bFROM\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],

        "INSERT": [
            r"\bINSERT\s+INTO\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],

        "UPDATE": [
            r"\bUPDATE\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],

        "DELETE": [
            r"\bDELETE\s+FROM\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],

        "DROP": [
            r"\bDROP\s+(?:TABLE|VIEW|DATABASE|SCHEMA)\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],

        "ALTER": [
            r"\bALTER\s+TABLE\s+(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],

        "TRUNCATE": [
            r"\bTRUNCATE\s+(?:TABLE\s+)?(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*)",
        ],
    }

    for pattern in patterns.get(
        operation,
        [],
    ):

        table = _extract_identifier(
            pattern,
            sql,
        )

        if table:
            return table

    return None


def extract_where(sql):
    """
    Extract the WHERE condition while respecting quoted strings.

    This avoids incorrectly stopping at a semicolon that appears
    inside a string literal.

    Example:

        WHERE name = 'O''Brien';

    remains intact.
    """

    if not sql:
        return None

    match = re.search(
        r"\bWHERE\b",
        sql,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    start = match.end()

    in_single_quote = False
    in_double_quote = False
    in_backtick = False

    i = start

    while i < len(sql):

        char = sql[i]

        # Handle escaped single quotes in SQL:
        # 'O''Brien'
        if (
            char == "'"
            and not in_double_quote
            and not in_backtick
        ):

            if (
                in_single_quote
                and i + 1 < len(sql)
                and sql[i + 1] == "'"
            ):

                i += 2
                continue

            in_single_quote = (
                not in_single_quote
            )

            i += 1
            continue

        # Double quoted identifiers/strings.
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

        # Backtick identifiers.
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

        # Semicolon outside quotes ends statement.
        if (
            char == ";"
            and not in_single_quote
            and not in_double_quote
            and not in_backtick
        ):

            return sql[start:i].strip()

        i += 1

    return sql[start:].strip()


def determine_scope_from_sql(sql, operation):
    """
    Determine syntactic scope without executing the SQL.

    This is NOT the same as database-aware row-count scope.

    Possible values:

        all_rows
        filtered
        unknown
    """

    if not sql:
        return "unknown"

    if operation in {
        "UPDATE",
        "DELETE",
    }:

        if extract_where(sql) is None:
            return "all_rows"

        return "filtered"

    if operation == "SELECT":

        if extract_where(sql) is None:
            return "all_rows"

        return "filtered"

    return "unknown"


def analyze_sql(sql):
    """
    Analyze SQL without executing it.

    Returns a stable dictionary used by the rest of GuardianAgent:

        {
            "operation": ...,
            "table": ...,
            "where": ...,
            "scope": ...,
            "sql": ...
        }

    The analyzer is schema-independent.
    """

    cleaned_sql = clean_sql(sql)

    operation = detect_operation(
        cleaned_sql
    )

    table = extract_table(
        cleaned_sql,
        operation,
    )

    where = extract_where(
        cleaned_sql
    )

    scope = determine_scope_from_sql(
        cleaned_sql,
        operation,
    )

    return {
        "operation": operation,
        "table": table,
        "where": where,
        "scope": scope,
        "sql": cleaned_sql,
    }


if __name__ == "__main__":

    test_queries = [

        "UPDATE employees "
        "SET salary = 70000 "
        "WHERE name = 'Arun';",

        """
        SELECT "Presentation of Credentials"
        FROM "US Ambassadors and Envoy Extraordinary to Colombia"
        WHERE "Termination of Mission" = 'August 15, 2000';
        """,

        """
        UPDATE `Football Team Results`
        SET `Points` = 10
        WHERE `Team` = 'Brazil';
        """,

        'SELECT * FROM "Some Table";',

        """
        INSERT INTO `Some Table`
        (`Name`, `Value`)
        VALUES ('A', 10);
        """,

        'DELETE FROM "Some Table" WHERE "ID" = 5;',

        'DROP TABLE "Some Table";',

        'ALTER TABLE "Some Table" ADD COLUMN "Age" INTEGER;',

        'TRUNCATE TABLE "Some Table";',
    ]

    print("=" * 70)
    print("SQL ANALYZER TESTS")
    print("=" * 70)

    for query in test_queries:

        print("\nSQL:")
        print(query.strip())

        result = analyze_sql(
            query
        )

        print("\nRESULT:")
        print(result)