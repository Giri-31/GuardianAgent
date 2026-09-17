# benchmark/dbbench_stage2.py

import json
import os
import re
import sqlite3
import sys
import time
import hashlib
import statistics
from pathlib import Path


# ============================================================
# PATH SETUP
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# DBBENCH LOADER
# ============================================================

from dbbench_loader import load_dbbench


# ============================================================
# GEMINI
# ============================================================

try:
    from google import genai
except ImportError:
    genai = None


MODEL = "gemini-3.6-flash"

# Number of NEW Gemini requests in one run.
#
# Keep this small while testing.
MAX_NEW_CASES = 20

OUTPUT_FILE = (
    ROOT
    / "benchmark"
    / "dbbench_stage2_results_v2.json"
)


# ============================================================
# GEMINI CLIENT
# ============================================================

def create_gemini_client():

    if genai is None:
        raise RuntimeError(
            "google-genai is not installed. "
            "Install it with: pip install google-genai"
        )

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set."
        )

    return genai.Client(
        api_key=api_key
    )


# ============================================================
# DATABASE CREATION
# ============================================================

def create_test_database(task):
    """
    Create an isolated temporary SQLite database.

    The real GuardianAgent company.db is NEVER touched.
    """

    conn = sqlite3.connect(":memory:")

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    table_data = task.get("table")

    if isinstance(table_data, dict):
        tables = [table_data]
    else:
        tables = table_data or []

    for table in tables:

        table_name = table["table_name"]

        table_info = table.get(
            "table_info",
            {}
        )

        columns = table_info.get(
            "columns",
            []
        )

        column_defs = []

        for column in columns:

            name = column["name"]

            dtype = str(
                column.get(
                    "type",
                    "TEXT"
                )
            ).upper()

            if dtype in {
                "INT",
                "INTEGER",
                "BIGINT",
                "SMALLINT",
                "TINYINT",
                "MEDIUMINT",
            }:
                sqlite_type = "INTEGER"

            elif dtype in {
                "FLOAT",
                "DOUBLE",
                "DECIMAL",
                "NUMERIC",
                "REAL",
            }:
                sqlite_type = "REAL"

            else:
                sqlite_type = "TEXT"

            column_defs.append(
                f"`{name}` {sqlite_type}"
            )

        if not column_defs:
            raise ValueError(
                f"No columns found for table {table_name}"
            )

        create_sql = (
            f"CREATE TABLE `{table_name}` "
            f"({', '.join(column_defs)})"
        )

        conn.execute(
            create_sql
        )

        rows = table_info.get(
            "rows",
            []
        )

        if rows:

            placeholders = ",".join(
                ["?"] * len(columns)
            )

            insert_sql = (
                f"INSERT INTO `{table_name}` "
                f"VALUES ({placeholders})"
            )

            for row in rows:

                values = []

                for value in row:

                    if value is None:
                        values.append(None)
                    else:
                        values.append(
                            str(value)
                        )

                conn.execute(
                    insert_sql,
                    values
                )

    conn.commit()

    return conn


# ============================================================
# MYSQL → SQLITE SQL ADAPTER
# ============================================================

def adapt_mysql_sql_to_sqlite(
    sql,
    task
):
    """
    DBBench originates from a MySQL environment.

    Some DBBench column names contain spaces, e.g.:

        Presentation of Credentials

    MySQL can accept the reference SQL representation used
    by DBBench, while SQLite requires the identifier to be
    quoted.

    This function quotes ONLY known column identifiers.

    It does not modify:
        'string literals'
        "already quoted identifiers"
        `already quoted identifiers`
    """

    if not sql:
        return sql

    table_data = task.get(
        "table"
    )

    if isinstance(table_data, dict):
        tables = [table_data]
    else:
        tables = table_data or []

    column_names = []

    for table in tables:

        table_info = table.get(
            "table_info",
            {}
        )

        for column in table_info.get(
            "columns",
            []
        ):

            name = column.get(
                "name"
            )

            if name:
                column_names.append(
                    name
                )

    column_names = sorted(
        set(column_names),
        key=len,
        reverse=True
    )

    if not column_names:
        return sql

    result = []

    i = 0
    n = len(sql)

    quote = None

    while i < n:

        ch = sql[i]

        # ----------------------------------------------------
        # Inside quoted string / identifier
        # ----------------------------------------------------

        if quote is not None:

            result.append(ch)

            if ch == quote:

                # Escaped quote:
                #
                # ''
                # ""
                # ``

                if (
                    i + 1 < n
                    and sql[i + 1] == quote
                ):

                    result.append(
                        sql[i + 1]
                    )

                    i += 2

                    continue

                quote = None

            i += 1

            continue

        # ----------------------------------------------------
        # Start quoted region
        # ----------------------------------------------------

        if ch in {
            "'",
            '"',
            "`"
        }:

            quote = ch

            result.append(ch)

            i += 1

            continue

        # ----------------------------------------------------
        # Try matching a known column
        # ----------------------------------------------------

        remaining = sql[i:]

        matched = False

        for column in column_names:

            if not remaining.startswith(
                column
            ):
                continue

            end = i + len(column)

            before = (
                sql[i - 1]
                if i > 0
                else ""
            )

            after = (
                sql[end]
                if end < n
                else ""
            )

            before_ok = (
                not before
                or not (
                    before.isalnum()
                    or before == "_"
                )
            )

            after_ok = (
                not after
                or not (
                    after.isalnum()
                    or after == "_"
                )
            )

            if before_ok and after_ok:

                result.append(
                    f"`{column}`"
                )

                i = end

                matched = True

                break

        if matched:
            continue

        result.append(ch)

        i += 1

    return "".join(result)


# ============================================================
# SQL EXECUTION
# ============================================================

def execute_generated_sql(
    conn,
    sql,
    task=None
):
    """
    Execute exactly one SQL statement.

    If task is provided, DBBench MySQL-style identifiers are
    adapted for SQLite first.
    """

    start = time.perf_counter()

    try:

        if not sql or not sql.strip():

            return {
                "status": "ERROR",
                "error": "Empty SQL",
                "rows": [],
                "elapsed_ms": 0
            }

        sql = sql.strip()

        # Remove markdown SQL fences.
        sql = re.sub(
            r"^```(?:sql)?\s*",
            "",
            sql,
            flags=re.IGNORECASE
        )

        sql = re.sub(
            r"\s*```$",
            "",
            sql
        )

        sql = sql.strip()

        # ----------------------------------------------------
        # Adapt DBBench SQL for SQLite.
        # ----------------------------------------------------

        if task is not None:

            sql = adapt_mysql_sql_to_sqlite(
                sql,
                task
            )

        # ----------------------------------------------------
        # Only ONE statement is permitted.
        # ----------------------------------------------------

        statements = [
            statement.strip()
            for statement in sql.split(";")
            if statement.strip()
        ]

        if len(statements) != 1:

            return {
                "status": "ERROR",
                "error": (
                    "Multiple SQL statements detected"
                ),
                "rows": [],
                "elapsed_ms": (
                    time.perf_counter()
                    - start
                ) * 1000
            }

        sql = statements[0]

        cursor = conn.cursor()

        cursor.execute(
            sql
        )

        # ----------------------------------------------------
        # Determine whether the statement returns rows.
        # ----------------------------------------------------

        is_read = bool(
            re.match(
                r"^\s*(SELECT|WITH|PRAGMA|EXPLAIN)",
                sql,
                flags=re.IGNORECASE
            )
        )

        rows = []

        if is_read:

            fetched = cursor.fetchall()

            rows = [
                tuple(row)
                for row in fetched
            ]

        else:

            conn.commit()

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000

        return {
            "status": "SUCCESS",
            "error": "",
            "rows": rows,
            "elapsed_ms": elapsed_ms
        }

    except Exception as exc:

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000

        return {
            "status": "ERROR",
            "error": str(exc),
            "rows": [],
            "elapsed_ms": elapsed_ms
        }


# ============================================================
# DBBENCH VALUE NORMALIZATION
# ============================================================

def normalize_value(value):

    if value is None:
        return "0"

    if isinstance(value, bytes):

        value = value.decode(
            "utf-8",
            errors="replace"
        )

    value = str(value).strip()

    if value.lower() in {
        "",
        "null",
        "none",
        "nan"
    }:
        return "0"

    # Remove surrounding single quotes.
    if (
        len(value) >= 2
        and value[0] == "'"
        and value[-1] == "'"
    ):
        value = value[1:-1]

    # Remove surrounding double quotes.
    if (
        len(value) >= 2
        and value[0] == '"'
        and value[-1] == '"'
    ):
        value = value[1:-1]

    # DBBench comparison strips %.
    if value.endswith("%"):
        value = value[:-1]

    # DBBench comparison ignores numeric comma formatting.
    value = value.replace(
        ",",
        ""
    )

    if value == "":
        return "0"

    return value


# ============================================================
# READ RESULT NORMALIZATION
# ============================================================

def normalize_rows(rows):

    normalized = []

    for row in rows:

        if not isinstance(
            row,
            (tuple, list)
        ):
            row = [row]

        normalized.append(
            tuple(
                normalize_value(
                    value
                )
                for value in row
            )
        )

    return normalized


def normalize_label(label):

    if label is None:
        return []

    if isinstance(
        label,
        str
    ):

        try:

            parsed = json.loads(
                label
            )

            if isinstance(
                parsed,
                list
            ):
                label = parsed

        except Exception:
            pass

    normalized = []

    if isinstance(
        label,
        list
    ):

        for item in label:

            if isinstance(
                item,
                (tuple, list)
            ):

                normalized.append(
                    tuple(
                        normalize_value(
                            x
                        )
                        for x in item
                    )
                )

            else:

                normalized.append(
                    (
                        normalize_value(
                            item
                        ),
                    )
                )

    else:

        normalized.append(
            (
                normalize_value(
                    label
                ),
            )
        )

    return normalized


def compare_select_answer(
    rows,
    label
):
    """
    Compare generated read results against DBBench label.
    """

    generated = normalize_rows(
        rows
    )

    expected = normalize_label(
        label
    )

    return (
        set(generated)
        == set(expected)
    )


# ============================================================
# DBBENCH WRITE HASH
# ============================================================

def mysql_concat_ws(
    separator,
    *values
):
    """
    Python equivalent of MySQL CONCAT_WS().

    NULL values are skipped.
    """

    parts = []

    for value in values:

        if value is None:
            continue

        if isinstance(
            value,
            bytes
        ):

            value = value.decode(
                "utf-8",
                errors="replace"
            )

        parts.append(
            str(value)
        )

    return separator.join(
        parts
    )


def calculate_row_hash(
    row
):
    """
    DBBench row hash:

        SUBSTRING(
            MD5(
                CONCAT_WS(',', ...)
            ),
            1,
            5
        )
    """

    row_string = mysql_concat_ws(
        ",",
        *row
    )

    digest = hashlib.md5(
        row_string.encode(
            "utf-8"
        )
    ).hexdigest()

    return digest[:5]


def get_table_columns(
    table_info
):

    columns = table_info.get(
        "table_info",
        {}
    ).get(
        "columns",
        []
    )

    return [
        column["name"]
        for column in columns
    ]


def calculate_single_table_hash(
    conn,
    table_info
):

    table_name = table_info[
        "table_name"
    ]

    columns = get_table_columns(
        table_info
    )

    if not columns:

        return hashlib.md5(
            b""
        ).hexdigest()

    column_sql = ", ".join(
        f"`{column}`"
        for column in columns
    )

    cursor = conn.cursor()

    cursor.execute(
        f"SELECT {column_sql} "
        f"FROM `{table_name}`"
    )

    rows = cursor.fetchall()

    row_hashes = [
        calculate_row_hash(
            row
        )
        for row in rows
    ]

    # Official DBBench behavior.
    row_hashes.sort()

    # IMPORTANT:
    # GROUP_CONCAT uses comma separator.
    combined = ",".join(
        row_hashes
    )

    return hashlib.md5(
        combined.encode(
            "utf-8"
        )
    ).hexdigest()


def calculate_table_state_hash(
    conn,
    task
):

    table_data = task[
        "table"
    ]

    if isinstance(
        table_data,
        dict
    ):
        tables = [
            table_data
        ]
    else:
        tables = table_data

    table_hashes = []

    for table_info in tables:

        table_hashes.append(
            calculate_single_table_hash(
                conn,
                table_info
            )
        )

    table_hashes.sort()

    if len(table_hashes) == 1:

        return table_hashes[0]

    return "_".join(
        table_hashes
    )


# ============================================================
# ANSWER_MD5
# ============================================================

def extract_answer_md5(
    answer_md5
):

    if answer_md5 is None:
        return None

    text = str(
        answer_md5
    )

    # Typical:
    #
    # [('09aa8fbf72f39362970f95a1276b957c',)]

    match = re.search(
        r"['\"]([0-9a-fA-F]{32})['\"]",
        text
    )

    if match:

        return match.group(
            1
        ).lower()

    match = re.search(
        r"\b([0-9a-fA-F]{32})\b",
        text
    )

    if match:

        return match.group(
            1
        ).lower()

    return None


# ============================================================
# GEMINI RESPONSE → SQL
# ============================================================

def extract_sql(
    response
):

    if response is None:
        return None

    if hasattr(
        response,
        "text"
    ):
        text = response.text
    else:
        text = str(
            response
        )

    if not text:
        return None

    text = text.strip()

    # SQL markdown block.
    match = re.search(
        r"```sql\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE
        | re.DOTALL
    )

    if match:

        return match.group(
            1
        ).strip()

    # Generic code block.
    match = re.search(
        r"```\s*(.*?)\s*```",
        text,
        flags=re.DOTALL
    )

    if match:

        candidate = match.group(
            1
        ).strip()

        if re.match(
            r"^(SELECT|INSERT|UPDATE|DELETE|WITH|ALTER|DROP|TRUNCATE)",
            candidate,
            flags=re.IGNORECASE
        ):

            return candidate

    # Plain SQL.
    match = re.search(
        r"\b(SELECT|INSERT|UPDATE|DELETE|WITH|ALTER|DROP|TRUNCATE)\b.*",
        text,
        flags=re.IGNORECASE
        | re.DOTALL
    )

    if match:

        candidate = match.group(
            0
        ).strip()

        if ";" in candidate:

            candidate = (
                candidate.split(
                    ";",
                    1
                )[0]
                + ";"
            )

        return candidate

    return None


# ============================================================
# SQL OPERATION
# ============================================================

def get_sql_operation(
    sql
):

    if not sql:
        return "UNKNOWN"

    match = re.match(
        r"^\s*(SELECT|INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE|WITH)",
        sql,
        flags=re.IGNORECASE
    )

    if not match:
        return "UNKNOWN"

    operation = match.group(
        1
    ).upper()

    if operation == "WITH":

        match2 = re.search(
            r"\)\s*(SELECT|INSERT|UPDATE|DELETE)",
            sql,
            flags=re.IGNORECASE
        )

        if match2:

            return match2.group(
                1
            ).upper()

    return operation


# ============================================================
# GEMINI SQL GENERATION
# ============================================================

def generate_sql(
    client,
    task
):

    table_data = task[
        "table"
    ]

    if isinstance(
        table_data,
        dict
    ):
        tables = [
            table_data
        ]
    else:
        tables = table_data

    schema_parts = []

    for table in tables:

        table_name = table[
            "table_name"
        ]

        columns = table[
            "table_info"
        ]["columns"]

        column_names = [
            column["name"]
            for column in columns
        ]

        schema_parts.append(
            f"Table `{table_name}` "
            f"columns: "
            f"{', '.join(column_names)}"
        )

    schema = "\n".join(
        schema_parts
    )

    description = task[
        "description"
    ]

    task_type = task.get(
        "type",
        ["other"]
    )

    prompt = f"""
Generate exactly ONE SQL statement for the following database task.

TASK:
{description}

DATABASE SCHEMA:
{schema}

DBBENCH TASK TYPE:
{task_type}

RULES:
1. Return exactly one SQL statement.
2. Use only the supplied tables and columns.
3. Do not explain the answer.
4. Do not use markdown.
5. Return SQL only.
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    return extract_sql(
        response
    )


# ============================================================
# GUARDIAN
# ============================================================

def build_neutral_intent(
    sql
):
    """
    DBBench does not provide GuardianAgent's structured
    user-intent representation.

    Therefore we do NOT fabricate target, field, value,
    or scope.

    Only the SQL operation is extracted.
    """

    operation = get_sql_operation(
        sql
    )

    return {
        "operation": operation,
        "target": "unknown",
        "field": "unknown",
        "value": "unknown",
        "scope": "unknown"
    }


def run_guardian(
    sql,
    task
):

    try:

        from guardian import guardian_check

        intent = build_neutral_intent(
            sql
        )

        return guardian_check(
            task[
                "description"
            ],
            sql,
            known_intent=intent
        )

    except Exception as exc:

        return {
            "error": str(exc)
        }


# ============================================================
# EVALUATE ONE TASK
# ============================================================

def evaluate_task(
    client,
    task
):

    start = time.perf_counter()

    result = {
        "case_id": task[
            "case_id"
        ],
        "type": task.get(
            "type",
            []
        ),
        "source": task.get(
            "source"
        ),
        "description": task.get(
            "description"
        ),
        "generated_sql": None,
        "sql_operation": None,
        "execution_status": None,
        "execution_error": None,
        "sql_correct": False,
        "guardian": None,
        "latency_ms": None
    }

    # --------------------------------------------------------
    # Generate SQL
    # --------------------------------------------------------

    try:

        generated_sql = generate_sql(
            client,
            task
        )

        result[
            "generated_sql"
        ] = generated_sql

    except Exception as exc:

        result[
            "execution_status"
        ] = "GEMINI_ERROR"

        result[
            "execution_error"
        ] = str(exc)

        result[
            "latency_ms"
        ] = (
            time.perf_counter()
            - start
        ) * 1000

        return result

    if not generated_sql:

        result[
            "execution_status"
        ] = "SQL_EXTRACTION_ERROR"

        result[
            "execution_error"
        ] = (
            "Could not extract SQL "
            "from Gemini response"
        )

        result[
            "latency_ms"
        ] = (
            time.perf_counter()
            - start
        ) * 1000

        return result

    # --------------------------------------------------------
    # Operation
    # --------------------------------------------------------

    result[
        "sql_operation"
    ] = get_sql_operation(
        generated_sql
    )

    # --------------------------------------------------------
    # Guardian
    # --------------------------------------------------------

    result[
        "guardian"
    ] = run_guardian(
        generated_sql,
        task
    )

    # --------------------------------------------------------
    # Temporary DB
    # --------------------------------------------------------

    conn = create_test_database(
        task
    )

    try:

        execution = execute_generated_sql(
            conn,
            generated_sql,
            task
        )

        result[
            "execution_status"
        ] = execution[
            "status"
        ]

        result[
            "execution_error"
        ] = execution.get(
            "error"
        )

        task_types = [
            str(x).upper()
            for x in task.get(
                "type",
                []
            )
        ]

        is_write_task = any(
            x in {
                "INSERT",
                "UPDATE",
                "DELETE"
            }
            for x in task_types
        )

        # ----------------------------------------------------
        # READ / QA TASK
        # ----------------------------------------------------

        if not is_write_task:

            if execution[
                "status"
            ] == "SUCCESS":

                result[
                    "sql_correct"
                ] = compare_select_answer(
                    execution[
                        "rows"
                    ],
                    task.get(
                        "label",
                        []
                    )
                )

        # ----------------------------------------------------
        # WRITE TASK
        # ----------------------------------------------------

        else:

            if execution[
                "status"
            ] == "SUCCESS":

                expected_hash = (
                    extract_answer_md5(
                        task.get(
                            "answer_md5"
                        )
                    )
                )

                actual_hash = (
                    calculate_table_state_hash(
                        conn,
                        task
                    )
                )

                result[
                    "expected_hash"
                ] = expected_hash

                result[
                    "actual_hash"
                ] = actual_hash

                result[
                    "sql_correct"
                ] = (
                    expected_hash is not None
                    and actual_hash
                    == expected_hash
                )

    finally:

        conn.close()

    result[
        "latency_ms"
    ] = (
        time.perf_counter()
        - start
    ) * 1000

    return result


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(
    results
):

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporary = (
        str(OUTPUT_FILE)
        + ".tmp"
    )

    with open(
        temporary,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(
        temporary,
        OUTPUT_FILE
    )


# ============================================================
# LOAD RESULTS
# ============================================================

def load_existing_results():

    if not OUTPUT_FILE.exists():
        return []

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(
                f
            )

        if isinstance(
            data,
            list
        ):
            return data

        return []

    except Exception:

        return []


# ============================================================
# SUMMARY
# ============================================================

def print_summary(
    results
):

    evaluated = [
        r
        for r in results
        if r.get(
            "execution_status"
        ) == "SUCCESS"
    ]

    correct = [
        r
        for r in evaluated
        if r.get(
            "sql_correct"
        )
    ]

    gemini_errors = [
        r
        for r in results
        if r.get(
            "execution_status"
        ) == "GEMINI_ERROR"
    ]

    sql_errors = [
        r
        for r in results
        if r.get(
            "execution_status"
        ) in {
            "ERROR",
            "SQL_EXTRACTION_ERROR"
        }
    ]

    latencies = [
        r["latency_ms"]
        for r in evaluated
        if r.get(
            "latency_ms"
        ) is not None
    ]

    print()

    print(
        "=" * 60
    )

    print(
        "DBBench Stage 2 Summary"
    )

    print(
        "=" * 60
    )

    print(
        f"Total results : {len(results)}"
    )

    print(
        f"Evaluated     : {len(evaluated)}"
    )

    print(
        f"Correct       : {len(correct)}"
    )

    print(
        f"Incorrect     : "
        f"{len(evaluated) - len(correct)}"
    )

    if evaluated:

        accuracy = (
            len(correct)
            / len(evaluated)
            * 100
        )

        print(
            f"Accuracy      : "
            f"{accuracy:.2f}%"
        )

    print(
        f"Gemini errors : "
        f"{len(gemini_errors)}"
    )

    print(
        f"SQL errors    : "
        f"{len(sql_errors)}"
    )

    if latencies:

        print(
            f"Mean latency  : "
            f"{statistics.mean(latencies):.4f} ms"
        )

        print(
            f"Median latency: "
            f"{statistics.median(latencies):.4f} ms"
        )

        print(
            f"Min latency   : "
            f"{min(latencies):.4f} ms"
        )

        print(
            f"Max latency   : "
            f"{max(latencies):.4f} ms"
        )

    print(
        f"Results saved : "
        f"{OUTPUT_FILE}"
    )

    print(
        "=" * 60
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()

    print(
        "=" * 60
    )

    print(
        "GuardianAgent — DBBench Stage 2"
    )

    print(
        "=" * 60
    )

    # --------------------------------------------------------
    # Load tasks
    # --------------------------------------------------------

    tasks = load_dbbench()

    print(
        f"DBBench tasks : {len(tasks)}"
    )

    # --------------------------------------------------------
    # Existing results
    # --------------------------------------------------------

    existing = load_existing_results()

    completed_ids = {
        r.get(
            "case_id"
        )
        for r in existing
        if r.get(
            "execution_status"
        ) != "GEMINI_ERROR"
    }

    print(
        f"Already done  : "
        f"{len(completed_ids)}"
    )

    remaining = [
        task
        for task in tasks
        if task[
            "case_id"
        ] not in completed_ids
    ]

    if MAX_NEW_CASES is not None:

        remaining = remaining[
            :MAX_NEW_CASES
        ]

    print(
        f"New cases     : "
        f"{len(remaining)}"
    )

    print(
        "Database mode : "
        "TEMPORARY IN-MEMORY"
    )

    print(
        "Guardian SQL execution : "
        "DISABLED"
    )

    print(
        f"Gemini model : "
        f"{MODEL}"
    )

    print()

    if not remaining:

        print(
            "No new cases to evaluate."
        )

        print_summary(
            existing
        )

        return

    # --------------------------------------------------------
    # Gemini
    # --------------------------------------------------------

    try:

        client = create_gemini_client()

    except Exception as exc:

        print(
            "Gemini initialization failed:"
        )

        print(
            exc
        )

        return

    results = list(
        existing
    )

    # --------------------------------------------------------
    # Evaluate
    # --------------------------------------------------------

    for index, task in enumerate(
        remaining,
        start=1
    ):

        print(
            f"[{index}/{len(remaining)}] "
            f"{task['case_id']} "
            f"{task.get('type', [])}"
        )

        result = evaluate_task(
            client,
            task
        )

        # Remove previous failed result for
        # the same case before saving the new one.
        results = [
            r
            for r in results
            if r.get(
                "case_id"
            )
            != task[
                "case_id"
            ]
        ]

        results.append(
            result
        )

        save_results(
            results
        )

        status = result.get(
            "execution_status"
        )

        if status == "GEMINI_ERROR":

            error = str(
                result.get(
                    "execution_error",
                    ""
                )
            )

            print(
                "  Gemini error:"
            )

            print(
                f"  {error}"
            )

            error_lower = error.lower()

            if (
                "429" in error_lower
                or "resource_exhausted"
                in error_lower
                or "quota"
                in error_lower
            ):

                print()
                print(
                    "Gemini quota detected."
                )

                print(
                    "Stopping benchmark run."
                )

                break

        elif status == "SUCCESS":

            print(
                f"  SQL operation : "
                f"{result.get('sql_operation')}"
            )

            print(
                f"  Correct       : "
                f"{result.get('sql_correct')}"
            )

            print(
                f"  Latency       : "
                f"{result.get('latency_ms', 0):.4f} ms"
            )

        else:

            print(
                f"  Status        : "
                f"{status}"
            )

            if result.get(
                "execution_error"
            ):

                print(
                    f"  Error         : "
                    f"{result['execution_error']}"
                )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print_summary(
        results
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()