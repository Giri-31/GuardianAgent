import hashlib
import json
import os
import re
import time

from dbbench_loader import load_dbbench

from guardian import guardian_check


# =============================================================
# Configuration
# =============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

RESULT_FILE = os.path.join(
    BASE_DIR,
    "benchmark",
    "dbbench_stage2_results.json"
)


# =============================================================
# DBBench helpers
# =============================================================

WRITE_TYPES = {
    "INSERT",
    "UPDATE",
    "DELETE"
}


def get_primary_type(task):

    task_type = task.get(
        "type",
        ["UNKNOWN"]
    )

    if isinstance(
        task_type,
        str
    ):
        return task_type.upper()

    if not task_type:
        return "UNKNOWN"

    return str(
        task_type[0]
    ).upper()


def is_write_task(task):

    return (
        get_primary_type(task)
        in WRITE_TYPES
    )


def get_reference_sql(task):

    sql = task.get(
        "reference_sql",
        ""
    )

    if sql is None:
        return ""

    return str(sql).strip()


def get_table_name(task):

    table = task.get(
        "table",
        {}
    )

    if isinstance(
        table,
        list
    ):

        if not table:
            return ""

        table = table[0]

    return table.get(
        "table_name",
        ""
    )


def build_operation_only_intent(sql):

    """
    DBBench safety mode.

    This does NOT pretend to know the user's exact target,
    field, value, or scope.

    It only derives the SQL operation.

    This is intentionally conservative because the current
    Guardian intent analyzer is specialized around the
    company.db employee schema.
    """

    operation = detect_sql_operation(
        sql
    )

    return {
        "operation": operation,
        "target": "unknown",
        "field": "unknown",
        "value": "unknown",
        "scope": "unknown"
    }


def detect_sql_operation(sql):

    if not sql:
        return "UNKNOWN"

    cleaned = (
        sql
        .strip()
        .upper()
    )

    match = re.match(
        r"^\s*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|WITH)\b",
        cleaned
    )

    if not match:
        return "UNKNOWN"

    operation = match.group(1)

    # WITH can contain SELECT/UPDATE/DELETE/INSERT.
    if operation == "WITH":

        if re.search(
            r"\bUPDATE\b",
            cleaned
        ):
            return "UPDATE"

        if re.search(
            r"\bDELETE\b",
            cleaned
        ):
            return "DELETE"

        if re.search(
            r"\bINSERT\b",
            cleaned
        ):
            return "INSERT"

        return "SELECT"

    return operation


# =============================================================
# SQL safety checks
# =============================================================

def contains_multiple_statements(sql):

    if not sql:
        return False

    # Remove a final semicolon.
    cleaned = sql.strip()

    if cleaned.endswith(";"):
        cleaned = cleaned[:-1]

    # A semicolon remaining in the statement means multiple
    # statements.
    return ";" in cleaned


def clean_sql(sql):

    if not sql:
        return ""

    sql = sql.strip()

    # Remove markdown code fences.
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

    return sql.strip()


# =============================================================
# Guardian adapter
# =============================================================

def run_guardian_for_dbbench(
    task,
    generated_sql,
    connection=None
):
    """
    Run Guardian on a DBBench task.

    NOTE:
    The current Guardian intent analyzer is not yet a fully
    domain-independent natural-language parser.

    Therefore DBBench evaluation currently uses an operation-only
    intent. This lets us evaluate the SQL safety layer without
    falsely claiming full intent-SQL semantic verification.
    """

    generated_sql = clean_sql(
        generated_sql
    )

    intent = build_operation_only_intent(
        generated_sql
    )

    table_name = get_table_name(
        task
    )

    start = time.perf_counter()

    result = guardian_check(
        user_request=task.get(
            "description",
            ""
        ),
        sql=generated_sql,
        known_intent=intent,
        connection=connection,
        table_name=table_name
    )

    elapsed_ms = (
        time.perf_counter()
        - start
    ) * 1000

    result["latency_ms"] = round(
        elapsed_ms,
        4
    )

    return result


# =============================================================
# Official-style answer normalization
# =============================================================

def normalize_value(value):

    if value is None:
        return "0"

    value = str(value).strip()

    # Remove surrounding quotes.
    value = value.strip(
        "'\""
    )

    # Percentage.
    if value.endswith("%"):

        value = value[:-1].strip()

    # Thousands separators.
    if "," in value:

        try:

            float(
                value.replace(
                    ",",
                    ""
                )
            )

            value = value.replace(
                ",",
                ""
            )

        except ValueError:
            pass

    lower = value.lower()

    special = {
        "",
        "none",
        "null",
        "undefined",
        "nan",
        "inf",
        "infinity",
        "-inf",
        "-infinity"
    }

    if lower in special:
        return "0"

    return value


def flatten_answer(value):

    if value is None:
        return ["0"]

    if isinstance(
        value,
        (list, tuple)
    ):

        output = []

        for item in value:

            if isinstance(
                item,
                (list, tuple)
            ):

                if len(item) == 1:

                    output.append(
                        normalize_value(
                            item[0]
                        )
                    )

                else:

                    output.append(
                        normalize_value(
                            item
                        )
                    )

            else:

                output.append(
                    normalize_value(
                        item
                    )
                )

        return output

    return [
        normalize_value(
            value
        )
    ]


def numeric_equal(
    a,
    b,
    tolerance=1e-2
):

    try:

        return abs(
            float(a)
            - float(b)
        ) <= tolerance

    except (
        ValueError,
        TypeError
    ):

        return False


def compare_read_answer(
    actual,
    expected
):
    """
    DBBench-style comparison for read tasks.
    """

    actual_values = flatten_answer(
        actual
    )

    expected_values = flatten_answer(
        expected
    )

    if (
        len(actual_values) == 1
        and len(expected_values) == 1
    ):

        a = actual_values[0]
        e = expected_values[0]

        if a == "0" and e == "0":
            return True

        if numeric_equal(
            a,
            e
        ):
            return True

        return a == e

    # Both numeric collections.
    if (
        all(
            numeric_equal(x, x)
            for x in actual_values
        )
        and all(
            numeric_equal(x, x)
            for x in expected_values
        )
    ):

        if (
            len(actual_values)
            != len(expected_values)
        ):
            return False

        used = [
            False
            for _ in expected_values
        ]

        for actual_value in actual_values:

            found = False

            for index, expected_value in enumerate(
                expected_values
            ):

                if used[index]:
                    continue

                if numeric_equal(
                    actual_value,
                    expected_value
                ):

                    used[index] = True
                    found = True
                    break

            if not found:
                return False

        return all(used)

    return (
        set(actual_values)
        == set(expected_values)
    )


# =============================================================
# Official-style DB state hashing
# =============================================================

def row_hash(row):

    values = []

    for value in row:

        if value is None:
            value = ""

        values.append(
            str(value)
        )

    row_string = ",".join(
        values
    )

    digest = hashlib.md5(
        row_string.encode(
            "utf-8"
        )
    ).hexdigest()

    return digest[:5]


def table_hash_from_rows(rows):

    hashes = [
        row_hash(row)
        for row in rows
    ]

    hashes.sort()

    joined = ",".join(
        hashes
    )

    return hashlib.md5(
        joined.encode(
            "utf-8"
        )
    ).hexdigest()


def extract_expected_hash(
    answer_md5
):

    if answer_md5 is None:
        return None

    if isinstance(
        answer_md5,
        str
    ):
        return answer_md5.strip()

    if isinstance(
        answer_md5,
        (list, tuple)
    ):

        if not answer_md5:
            return None

        first = answer_md5[0]

        if isinstance(
            first,
            (list, tuple)
        ):

            if not first:
                return None

            return str(
                first[0]
            ).strip()

        return str(
            first
        ).strip()

    return str(
        answer_md5
    ).strip()


# =============================================================
# DBBench result record
# =============================================================

def build_result_record(
    task,
    generated_sql,
    guardian_result,
    status,
    error=None
):

    return {
        "case_id": task.get(
            "case_id"
        ),

        "type": get_primary_type(
            task
        ),

        "source": task.get(
            "source",
            ""
        ),

        "description": task.get(
            "description",
            ""
        ),

        "generated_sql": generated_sql,

        "guardian": guardian_result,

        "gateway_decision": (
            guardian_result
            .get("risk", {})
            .get(
                "decision",
                "UNKNOWN"
            )
            if guardian_result
            else "UNKNOWN"
        ),

        "status": status,

        "error": error
    }


# =============================================================
# IMPORTANT: database execution
# =============================================================

def execute_dbbench_task(
    task,
    generated_sql,
    connection
):
    """
    Execute ONE generated SQL statement.

    This function deliberately requires an externally supplied
    DB connection.

    We do NOT silently create an SQLite approximation here.

    That prevents accidental reporting of a non-equivalent
    SQLite run as official DBBench.
    """

    generated_sql = clean_sql(
        generated_sql
    )

    if not generated_sql:
        raise ValueError(
            "Generated SQL is empty."
        )

    if contains_multiple_statements(
        generated_sql
    ):

        raise ValueError(
            "Multiple SQL statements are not allowed."
        )

    cursor = connection.cursor()

    cursor.execute(
        generated_sql
    )

    operation = detect_sql_operation(
        generated_sql
    )

    if operation in {
        "SELECT"
    }:

        rows = cursor.fetchall()

        return {
            "operation": operation,
            "rows": rows
        }

    connection.commit()

    return {
        "operation": operation,
        "rows": []
    }


# =============================================================
# Evaluate one task
# =============================================================

def evaluate_task(
    task,
    generated_sql,
    connection
):
    """
    Safety-gated DBBench evaluation.

    Decision semantics:

        ALLOW
            SQL executes.

        CONFIRM
            SQL is NOT automatically executed.

            This is important: an automated benchmark has
            no human confirmation.

        BLOCK
            SQL is NOT executed.

    Therefore this evaluates the Guardian gateway's
    conservative safety behavior.

    It does NOT claim that CONFIRM would preserve task
    utility under human approval.
    """

    generated_sql = clean_sql(
        generated_sql
    )

    guardian_result = (
        run_guardian_for_dbbench(
            task,
            generated_sql,
            connection
        )
    )

    decision = (
        guardian_result
        .get("risk", {})
        .get(
            "decision",
            "UNKNOWN"
        )
    )

    # ---------------------------------------------------------
    # BLOCK
    # ---------------------------------------------------------

    if decision == "BLOCK":

        return build_result_record(
            task,
            generated_sql,
            guardian_result,
            status="BLOCKED_BY_GUARDIAN"
        )

    # ---------------------------------------------------------
    # CONFIRM
    # ---------------------------------------------------------

    if decision == "CONFIRM":

        return build_result_record(
            task,
            generated_sql,
            guardian_result,
            status="CONFIRM_REQUIRED"
        )

    # ---------------------------------------------------------
    # UNKNOWN
    # ---------------------------------------------------------

    if decision != "ALLOW":

        return build_result_record(
            task,
            generated_sql,
            guardian_result,
            status="GUARDIAN_ERROR",
            error=(
                "Guardian returned unexpected "
                f"decision: {decision}"
            )
        )

    # ---------------------------------------------------------
    # ALLOW
    # ---------------------------------------------------------

    try:

        execution = execute_dbbench_task(
            task,
            generated_sql,
            connection
        )

        result = build_result_record(
            task,
            generated_sql,
            guardian_result,
            status="EXECUTED"
        )

        result["execution"] = execution

        return result

    except Exception as exc:

        return build_result_record(
            task,
            generated_sql,
            guardian_result,
            status="EXECUTION_ERROR",
            error=str(exc)
        )


# =============================================================
# Save results
# =============================================================

def save_results(
    results,
    path=RESULT_FILE
):

    os.makedirs(
        os.path.dirname(path),
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            results,
            file,
            indent=2,
            ensure_ascii=False
        )


# =============================================================
# Summary
# =============================================================

def summarize_results(
    results
):

    total = len(results)

    executed = sum(
        r["status"] == "EXECUTED"
        for r in results
    )

    blocked = sum(
        r["status"]
        == "BLOCKED_BY_GUARDIAN"
        for r in results
    )

    confirm = sum(
        r["status"]
        == "CONFIRM_REQUIRED"
        for r in results
    )

    execution_errors = sum(
        r["status"]
        == "EXECUTION_ERROR"
        for r in results
    )

    guardian_errors = sum(
        r["status"]
        == "GUARDIAN_ERROR"
        for r in results
    )

    print()
    print("=" * 60)
    print("DBBENCH RUN SUMMARY")
    print("=" * 60)

    print(
        f"Total processed       : {total}"
    )

    print(
        f"Executed              : {executed}"
    )

    print(
        f"Blocked               : {blocked}"
    )

    print(
        f"Confirmation required : {confirm}"
    )

    print(
        f"Execution errors      : {execution_errors}"
    )

    print(
        f"Guardian errors       : {guardian_errors}"
    )

    print("=" * 60)


# =============================================================
# Main
# =============================================================

def main():

    print(
        "Loading AgentBench DBBench..."
    )

    tasks = load_dbbench()

    print(
        f"Loaded {len(tasks)} tasks."
    )

    print()
    print(
        "IMPORTANT:"
    )
    print(
        "This runner requires a real DBBench-compatible "
        "database connection."
    )
    print(
        "It intentionally does NOT silently substitute "
        "SQLite for MySQL."
    )
    print()

    raise RuntimeError(
        "DBBench database connection is not configured yet. "
        "Do not run the benchmark until the MySQL DBBench "
        "environment is configured."
    )


if __name__ == "__main__":
    main()