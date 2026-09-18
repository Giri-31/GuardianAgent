import re


# ============================================================
# SQL Analyzer
# ============================================================
#
# IMPORTANT:
# This module is schema-independent.
#
# It does NOT know about:
#   employees
#   salary
#   Arun
#   IT
#   any specific database
#
# All information is extracted from the SQL statement itself.
#
# The analyzer does NOT execute SQL.
# ============================================================


SUPPORTED_OPERATIONS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
}


def analyze_sql(sql):
    """
    Analyze an SQL statement without executing it.

    Returns:

        operation
        table
        where
        scope
        sql

    The analyzer is independent of database schema.
    """

    if sql is None:
        sql = ""

    sql_clean = str(sql).strip()

    if not sql_clean:

        return {
            "operation": "UNKNOWN",
            "table": "unknown",
            "where": None,
            "scope": "unknown",
            "sql": sql_clean
        }

    # --------------------------------------------------------
    # Remove markdown fences if an LLM returned:
    #
    # ```sql
    # SELECT ...
    # ```
    # --------------------------------------------------------

    sql_clean = clean_sql(sql_clean)

    # --------------------------------------------------------
    # Detect operation
    # --------------------------------------------------------

    operation = detect_operation(
        sql_clean
    )

    # --------------------------------------------------------
    # Detect table
    # --------------------------------------------------------

    table = extract_table(
        sql_clean,
        operation
    )

    # --------------------------------------------------------
    # Detect WHERE
    # --------------------------------------------------------

    where = extract_where(
        sql_clean
    )

    # --------------------------------------------------------
    # Determine syntactic scope
    #
    # IMPORTANT:
    #
    # This is SQL scope, NOT database row count.
    #
    # filtered  -> WHERE exists
    # all_rows  -> no WHERE for row-affecting/read statement
    # unknown   -> cannot determine
    #
    # Actual number of matching rows is handled separately
    # by the scope analyzer when a database connection exists.
    # --------------------------------------------------------

    if where is not None:

        scope = "filtered"

    elif operation in {
        "SELECT",
        "UPDATE",
        "DELETE"
    }:

        scope = "all_rows"

    else:

        scope = "unknown"

    return {
        "operation": operation,
        "table": table,
        "where": where,
        "scope": scope,
        "sql": sql_clean
    }


# ============================================================
# SQL cleaning
# ============================================================

def clean_sql(sql):

    sql = sql.strip()

    # Remove opening markdown fence.
    sql = re.sub(
        r"^\s*```(?:sql)?\s*",
        "",
        sql,
        flags=re.IGNORECASE
    )

    # Remove closing markdown fence.
    sql = re.sub(
        r"\s*```\s*$",
        "",
        sql
    )

    return sql.strip()


# ============================================================
# Operation detection
# ============================================================

def detect_operation(sql):

    """
    Detect the top-level SQL operation.

    Supports normal statements and common WITH statements.
    """

    match = re.match(
        r"^\s*([A-Za-z]+)\b",
        sql
    )

    if not match:

        return "UNKNOWN"

    first_keyword = (
        match.group(1)
        .upper()
    )

    if first_keyword in SUPPORTED_OPERATIONS:

        return first_keyword

    # --------------------------------------------------------
    # Common Table Expression:
    #
    # WITH x AS (...)
    # SELECT ...
    #
    # WITH x AS (...)
    # UPDATE ...
    # --------------------------------------------------------

    if first_keyword == "WITH":

        return detect_with_operation(
            sql
        )

    return "UNKNOWN"


def detect_with_operation(sql):

    """
    Detect the actual operation of a WITH statement.

    This is intentionally conservative.
    """

    upper_sql = sql.upper()

    # Find the end of the CTE section.
    #
    # Rather than trying to implement a complete SQL parser,
    # identify the first operation keyword occurring after the
    # CTE definitions.

    candidates = [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE"
    ]

    positions = []

    for keyword in candidates:

        for match in re.finditer(
            rf"\b{keyword}\b",
            upper_sql
        ):

            positions.append(
                (
                    match.start(),
                    keyword
                )
            )

    if not positions:

        return "UNKNOWN"

    positions.sort(
        key=lambda x: x[0]
    )

    return positions[0][1]


# ============================================================
# Identifier extraction
# ============================================================

def read_identifier(
    text,
    position
):
    """
    Read one SQL identifier beginning at `position`.

    Supports:

        employees

        "Employee Table"

        `Employee Table`

        [Employee Table]

    Returns:

        (identifier, next_position)

    or:

        (None, position)
    """

    length = len(text)

    while (
        position < length
        and text[position].isspace()
    ):

        position += 1

    if position >= length:

        return None, position

    char = text[position]

    # --------------------------------------------------------
    # Double quoted identifier
    # --------------------------------------------------------

    if char == '"':

        end = position + 1

        while end < length:

            if text[end] == '"':

                # SQL escaped quote:
                #
                # ""
                #

                if (
                    end + 1 < length
                    and text[end + 1] == '"'
                ):

                    end += 2
                    continue

                return (
                    text[
                        position + 1:end
                    ],
                    end + 1
                )

            end += 1

        return None, position

    # --------------------------------------------------------
    # MySQL backtick identifier
    # --------------------------------------------------------

    if char == "`":

        end = position + 1

        while end < length:

            if text[end] == "`":

                if (
                    end + 1 < length
                    and text[end + 1] == "`"
                ):

                    end += 2
                    continue

                return (
                    text[
                        position + 1:end
                    ],
                    end + 1
                )

            end += 1

        return None, position

    # --------------------------------------------------------
    # SQL Server-style identifier
    # --------------------------------------------------------

    if char == "[":

        end = text.find(
            "]",
            position + 1
        )

        if end != -1:

            return (
                text[
                    position + 1:end
                ],
                end + 1
            )

        return None, position

    # --------------------------------------------------------
    # Normal identifier
    # --------------------------------------------------------

    match = re.match(
        r"[A-Za-z_][A-Za-z0-9_$]*",
        text[position:]
    )

    if not match:

        return None, position

    identifier = match.group(0)

    return (
        identifier,
        position + len(identifier)
    )


# ============================================================
# Table extraction
# ============================================================

def extract_table(
    sql,
    operation
):
    """
    Extract the primary table associated with the SQL operation.

    This function does not know any table names beforehand.
    """

    if operation == "SELECT":

        match = re.search(
            r"\bFROM\b",
            sql,
            flags=re.IGNORECASE
        )

    elif operation == "UPDATE":

        match = re.search(
            r"\bUPDATE\b",
            sql,
            flags=re.IGNORECASE
        )

    elif operation == "INSERT":

        match = re.search(
            r"\bINTO\b",
            sql,
            flags=re.IGNORECASE
        )

    elif operation == "DELETE":

        match = re.search(
            r"\bFROM\b",
            sql,
            flags=re.IGNORECASE
        )

    elif operation == "DROP":

        match = re.search(
            r"\b(?:TABLE|DATABASE)\b",
            sql,
            flags=re.IGNORECASE
        )

    elif operation == "ALTER":

        match = re.search(
            r"\bTABLE\b",
            sql,
            flags=re.IGNORECASE
        )

    elif operation == "TRUNCATE":

        match = re.search(
            r"\b(?:TABLE)?\s*",
            sql,
            flags=re.IGNORECASE
        )

        # For TRUNCATE, search explicitly after the keyword.
        match = re.search(
            r"\bTRUNCATE\b"
            r"(?:\s+TABLE)?\s+",
            sql,
            flags=re.IGNORECASE
        )

    else:

        return "unknown"

    if not match:

        return "unknown"

    identifier, _ = read_identifier(
        sql,
        match.end()
    )

    if identifier is None:

        return "unknown"

    return identifier


# ============================================================
# WHERE extraction
# ============================================================

def extract_where(sql):

    """
    Extract the WHERE condition.

    This preserves the original condition rather than trying
    to interpret its semantics.
    """

    match = re.search(
        r"\bWHERE\b",
        sql,
        flags=re.IGNORECASE
    )

    if not match:

        return None

    start = match.end()

    # --------------------------------------------------------
    # Find the statement terminator.
    #
    # We deliberately do not split on semicolons inside quotes.
    # --------------------------------------------------------

    end = find_statement_end(
        sql,
        start
    )

    where = (
        sql[start:end]
        .strip()
    )

    if not where:

        return None

    return where


def find_statement_end(
    sql,
    start
):
    """
    Find the semicolon terminating the statement while ignoring
    semicolons inside quoted strings/identifiers.
    """

    quote = None
    i = start

    while i < len(sql):

        char = sql[i]

        if quote is not None:

            if char == quote:

                # Escaped quote:
                #
                # ''
                # ""
                # ``
                #

                if (
                    i + 1 < len(sql)
                    and sql[i + 1] == quote
                ):

                    i += 2
                    continue

                quote = None

            i += 1
            continue

        if char in (
            "'",
            '"',
            "`"
        ):

            quote = char
            i += 1
            continue

        if char == ";":

            return i

        i += 1

    return len(sql)


# ============================================================
# Manual tests
# ============================================================

if __name__ == "__main__":

    test_queries = [

        # Existing Guardian SQL
        "UPDATE employees "
        "SET salary = 70000 "
        "WHERE name = 'Arun';",

        # DBBench quoted table/column names
        'SELECT "Presentation of Credentials" '
        'FROM "US Ambassadors and Envoy Extraordinary to Colombia" '
        'WHERE "Termination of Mission" = '
        "'August 15, 2000';",

        # MySQL identifiers
        "UPDATE `Football Team Results` "
        "SET `Points` = 10 "
        "WHERE `Team` = 'Brazil';",

        # Quoted table
        'SELECT * FROM "Some Table";',

        # INSERT
        "INSERT INTO `Some Table` "
        "(`Name`, `Value`) "
        "VALUES ('A', 10);",

        # DELETE
        'DELETE FROM "Some Table" '
        'WHERE "ID" = 5;',

        # DROP
        'DROP TABLE "Some Table";',

        # ALTER
        'ALTER TABLE "Some Table" ADD COLUMN "Age" INTEGER;',

        # TRUNCATE
        'TRUNCATE TABLE "Some Table";',

        # No WHERE
        "UPDATE some_table "
        "SET value = 10;",

        # WHERE containing a semicolon in a string
        "SELECT * FROM some_table "
        "WHERE name = 'A;B';",

    ]

    for sql in test_queries:

        print("=" * 70)
        print(sql)

        result = analyze_sql(
            sql
        )

        print(result)