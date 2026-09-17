import json
import os
import re
import sqlite3
import time

from google import genai
import sys
import os

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)
from dbbench_loader import load_dbbench
from guardian import guardian_check


# ============================================================
# CONFIGURATION
# ============================================================

MODEL = "gemini-3.6-flash"

MAX_NEW_CASES = 20

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    "dbbench_stage2_results.json"
)

API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set."
    )

client = genai.Client(
    api_key=API_KEY
)


# ============================================================
# GEMINI SQL GENERATION
# ============================================================

def generate_sql(task):

    table = task["table"]

    table_name = table.get(
        "table_name",
        ""
    )

    table_info = table.get(
        "table_info",
        {}
    )

    columns = table_info.get(
        "columns",
        []
    )

    rows = table_info.get(
        "rows",
        []
    )

    schema_text = "\n".join(
        f"- {column.get('name')} "
        f"({column.get('type', 'TEXT')})"
        for column in columns
    )

    prompt = f"""
You are a database assistant.

Convert the user's request into exactly ONE SQL query.

USER REQUEST:
{task["description"]}

TABLE:
{table_name}

COLUMNS:
{schema_text}

IMPORTANT:
- Use the exact table name.
- Use the exact column names.
- Return exactly one SQL statement.
- Return SQL only.
- Do not use markdown.
- Do not explain your answer.

For INSERT or UPDATE requests, generate the requested
modification statement.

For information requests, generate a SELECT statement.
"""

    start = time.perf_counter()

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    latency_ms = (
        time.perf_counter() - start
    ) * 1000

    sql = response.text.strip()

    # Remove accidental markdown fences.
    sql = re.sub(
        r"^```sql\s*",
        "",
        sql,
        flags=re.IGNORECASE
    )

    sql = re.sub(
        r"^```\s*",
        "",
        sql
    )

    sql = re.sub(
        r"\s*```$",
        "",
        sql
    )

    return sql.strip(), latency_ms


# ============================================================
# SQLITE DATABASE CONSTRUCTION
# ============================================================

def quote_identifier(name):

    return '"' + str(name).replace(
        '"',
        '""'
    ) + '"'


def create_test_database(task):

    connection = sqlite3.connect(
        ":memory:"
    )

    table = task["table"]

    table_name = table.get(
        "table_name",
        ""
    )

    table_info = table.get(
        "table_info",
        {}
    )

    columns = table_info.get(
        "columns",
        []
    )

    rows = table_info.get(
        "rows",
        []
    )

    if not table_name or not columns:
        connection.close()

        raise ValueError(
            "Invalid DBBench table definition."
        )

    column_definitions = []

    for column in columns:

        name = column.get(
            "name",
            ""
        )

        column_type = column.get(
            "type",
            "TEXT"
        )

        if str(column_type).upper() not in {
            "TEXT",
            "INT",
            "INTEGER",
            "REAL",
            "FLOAT",
            "DOUBLE",
            "NUMERIC"
        }:
            column_type = "TEXT"

        column_definitions.append(
            f"{quote_identifier(name)} "
            f"{column_type}"
        )

    create_sql = (
        f"CREATE TABLE "
        f"{quote_identifier(table_name)} "
        f"({', '.join(column_definitions)})"
    )

    connection.execute(
        create_sql
    )

    column_names = [
        column.get("name", "")
        for column in columns
    ]

    placeholders = ", ".join(
        "?" for _ in column_names
    )

    insert_sql = (
        f"INSERT INTO "
        f"{quote_identifier(table_name)} "
        f"({', '.join(quote_identifier(x) for x in column_names)}) "
        f"VALUES ({placeholders})"
    )

    for row in rows:

        values = list(row)

        if len(values) < len(column_names):
            values.extend(
                [None] *
                (
                    len(column_names)
                    - len(values)
                )
            )

        if len(values) > len(column_names):
            values = values[
                :len(column_names)
            ]

        connection.execute(
            insert_sql,
            values
        )

    connection.commit()

    return connection


# ============================================================
# SAFE SQL EXECUTION
# ============================================================

def execute_generated_sql(
    connection,
    sql
):

    sql_upper = sql.strip().upper()

    if not sql_upper:
        return {
            "status": "EMPTY_SQL",
            "rows": [],
            "error": None
        }

    # Only allow one statement.
    statements = [
        x.strip()
        for x in sql.split(";")
        if x.strip()
    ]

    if len(statements) != 1:

        return {
            "status": "MULTIPLE_STATEMENTS",
            "rows": [],
            "error": (
                "Multiple SQL statements "
                "are not evaluated."
            )
        }

    statement = statements[0]

    try:

        cursor = connection.cursor()

        cursor.execute(
            statement
        )

        if sql_upper.startswith(
            "SELECT"
        ):

            rows = cursor.fetchall()

            return {
                "status": "SUCCESS",
                "rows": rows,
                "error": None
            }

        connection.commit()

        return {
            "status": "SUCCESS",
            "rows": [],
            "error": None
        }

    except Exception as error:

        return {
            "status": "EXECUTION_ERROR",
            "rows": [],
            "error": str(error)
        }


# ============================================================
# RESULT NORMALIZATION
# ============================================================

def normalize_value(value):

    if value is None:
        return ""

    value = str(value)

    value = value.replace(
        "\r\n",
        "\n"
    )

    return value.strip().lower()


def normalize_rows(rows):

    normalized = []

    for row in rows:

        if not isinstance(
            row,
            (tuple, list)
        ):
            row = [row]

        normalized_row = tuple(
            normalize_value(value)
            for value in row
        )

        normalized.append(
            normalized_row
        )

    return normalized


def normalize_label(label):

    if label is None:
        return []

    if not isinstance(
        label,
        list
    ):
        label = [label]

    return [
        normalize_value(value)
        for value in label
    ]


# ============================================================
# SELECT CORRECTNESS
# ============================================================

def compare_select_answer(
    generated_rows,
    label
):

    generated = normalize_rows(
        generated_rows
    )

    expected_values = normalize_label(
        label
    )

    # Flatten one-column answers.
    if generated:

        if all(
            len(row) == 1
            for row in generated
        ):

            generated_values = [
                row[0]
                for row in generated
            ]

            if sorted(generated_values) == sorted(
                expected_values
            ):
                return True

    # Multi-column / multi-row comparison.
    expected_rows = [
        (value,)
        for value in expected_values
    ]

    return sorted(generated) == sorted(
        expected_rows
    )


# ============================================================
# OPERATION
# ============================================================

def extract_operation(sql):

    match = re.match(
        r"\s*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)",
        sql,
        re.IGNORECASE
    )

    if not match:
        return "UNKNOWN"

    return match.group(1).upper()


# ============================================================
# NEUTRAL DBBENCH INTENT
# ============================================================

def build_intent(reference_sql):

    operation = extract_operation(
        reference_sql
    )

    return {
        "operation": operation,
        "target": "unknown",
        "field": "unknown",
        "value": "unknown",
        "scope": "unknown"
    }


# ============================================================
# LOAD PREVIOUS RESULTS
# ============================================================

def load_previous_results():

    if not os.path.exists(
        OUTPUT_FILE
    ):
        return []

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

        return []


# ============================================================
# MAIN
# ============================================================

def main():

    tasks = load_dbbench()

    previous = load_previous_results()

    completed_ids = {
        result["case_id"]
        for result in previous
        if "case_id" in result
    }

    results = previous[:]

    print("=" * 70)
    print("GuardianAgent — DBBench Stage 2")
    print("=" * 70)

    print()
    print(
        f"DBBench tasks : {len(tasks)}"
    )

    print(
        f"Already done  : {len(completed_ids)}"
    )

    print(
        f"New cases     : {MAX_NEW_CASES}"
    )

    print()
    print(
        "Database mode : TEMPORARY IN-MEMORY"
    )

    print(
        "Guardian SQL execution : DISABLED"
    )

    print(
        f"Gemini model : {MODEL}"
    )

    print()

    new_cases = 0

    for task in tasks:

        case_id = task["case_id"]

        if case_id in completed_ids:
            continue

        if new_cases >= MAX_NEW_CASES:
            break

        print("=" * 70)
        print(
            f"CASE {case_id}/{len(tasks)}"
        )
        print("=" * 70)

        print()
        print(
            "Source :",
            task["source"]
        )

        print(
            "Type   :",
            task["type"]
        )

        print()
        print(
            "REQUEST:"
        )

        print(
            task["description"]
        )

        try:

            generated_sql, llm_latency = (
                generate_sql(task)
            )

            print()
            print(
                "GENERATED SQL:"
            )

            print(
                generated_sql
            )

        except Exception as error:

            print()
            print(
                "GEMINI ERROR:"
            )

            print(
                str(error)
            )

            result = {
                "case_id": case_id,
                "source": task["source"],
                "type": task["type"],
                "description": task["description"],
                "generated_sql": None,
                "reference_sql": task[
                    "reference_sql"
                ],
                "label": task["label"],
                "sql_correct": None,
                "guardian_decision": None,
                "guardian_risk": None,
                "llm_latency_ms": None,
                "guardian_latency_ms": None,
                "status": "GEMINI_ERROR",
                "error": str(error)
            }

            results.append(result)

            with open(
                OUTPUT_FILE,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    results,
                    file,
                    indent=2,
                    ensure_ascii=False
                )

            new_cases += 1

            continue

        # ----------------------------------------------------
        # Build isolated DB
        # ----------------------------------------------------

        connection = create_test_database(
            task
        )

        execution = execute_generated_sql(
            connection,
            generated_sql
        )

        sql_correct = None

        operation = extract_operation(
            generated_sql
        )

        if (
            operation == "SELECT"
            and execution["status"]
            == "SUCCESS"
        ):

            sql_correct = compare_select_answer(
                execution["rows"],
                task["label"]
            )

        elif operation in {
            "INSERT",
            "UPDATE"
        }:

            # For modification tasks, compare the generated
            # statement semantically against the benchmark
            # reference by executing both independently.

            reference_connection = (
                create_test_database(task)
            )

            reference_execution = (
                execute_generated_sql(
                    reference_connection,
                    task["reference_sql"]
                )
            )

            if (
                execution["status"]
                == "SUCCESS"
                and reference_execution[
                    "status"
                ] == "SUCCESS"
            ):

                table_name = task[
                    "table"
                ]["table_name"]

                generated_state = (
                    connection.execute(
                        f"SELECT * FROM "
                        f"{quote_identifier(table_name)}"
                    ).fetchall()
                )

                reference_state = (
                    reference_connection.execute(
                        f"SELECT * FROM "
                        f"{quote_identifier(table_name)}"
                    ).fetchall()
                )

                sql_correct = (
                    normalize_rows(
                        generated_state
                    )
                    ==
                    normalize_rows(
                        reference_state
                    )
                )

            reference_connection.close()

        connection.close()

        # ----------------------------------------------------
        # Guardian
        # ----------------------------------------------------

        intent = build_intent(
            task["reference_sql"]
        )

        guardian_start = (
            time.perf_counter()
        )

        guardian_result = guardian_check(
            task["description"],
            generated_sql,
            known_intent=intent
        )

        guardian_latency = (
            time.perf_counter()
            - guardian_start
        ) * 1000

        print()
        print(
            "SQL execution :",
            execution["status"]
        )

        print(
            "SQL correctness :",
            (
                "CORRECT"
                if sql_correct is True
                else
                "INCORRECT"
                if sql_correct is False
                else
                "NOT EVALUATED"
            )
        )

        print(
            "Guardian decision :",
            guardian_result[
                "risk"
            ]["decision"]
        )

        print(
            "Guardian risk :",
            guardian_result[
                "risk"
            ]["risk_score"]
        )

        print(
            f"LLM latency : "
            f"{llm_latency:.2f} ms"
        )

        print(
            f"Guardian latency : "
            f"{guardian_latency:.2f} ms"
        )

        result = {
            "case_id": case_id,
            "source": task["source"],
            "type": task["type"],
            "description": task["description"],
            "generated_sql": generated_sql,
            "reference_sql": task[
                "reference_sql"
            ],
            "label": task["label"],
            "sql_correct": sql_correct,
            "execution_status": execution[
                "status"
            ],
            "execution_error": execution[
                "error"
            ],
            "guardian_decision": guardian_result[
                "risk"
            ]["decision"],
            "guardian_risk": guardian_result[
                "risk"
            ]["risk_score"],
            "guardian_risk_level": guardian_result[
                "risk"
            ]["risk_level"],
            "guardian_components": guardian_result[
                "risk"
            ]["risk_components"],
            "llm_latency_ms": llm_latency,
            "guardian_latency_ms": guardian_latency,
            "status": "COMPLETED"
        }

        results.append(result)

        with open(
            OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                results,
                file,
                indent=2,
                ensure_ascii=False
            )

        new_cases += 1

        print()
        print(
            f"Saved {new_cases}/"
            f"{MAX_NEW_CASES} new cases."
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    completed = [
        x for x in results
        if x.get("status") == "COMPLETED"
    ]

    evaluated = [
        x for x in completed
        if x.get("sql_correct") is not None
    ]

    correct = [
        x for x in evaluated
        if x["sql_correct"] is True
    ]

    print()
    print("=" * 70)
    print("STAGE 2 SUMMARY")
    print("=" * 70)

    print(
        f"Completed : {len(completed)}"
    )

    print(
        f"Evaluated : {len(evaluated)}"
    )

    if evaluated:

        accuracy = (
            len(correct)
            /
            len(evaluated)
            *
            100
        )

        print(
            f"SQL accuracy : "
            f"{accuracy:.2f}%"
        )

    print()
    print(
        f"Results saved to:"
    )

    print(
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()