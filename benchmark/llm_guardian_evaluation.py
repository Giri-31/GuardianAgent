import os
import sys
import json
import re
import time
import sqlite3
from pathlib import Path

from google import genai


# ============================================================
# PROJECT PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dbbench_loader import load_dbbench
from guardian import guardian_check


# ============================================================
# CONFIGURATION
# ============================================================

PILOT_SIZE = 5

MODEL_NAME = "gemini-3.6-flash"

OUTPUT_FILE = (
    PROJECT_ROOT
    / "benchmark"
    / "llm_guardian_pilot_results.json"
)


# ============================================================
# GEMINI CLIENT
# ============================================================

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is not set."
    )

client = genai.Client(api_key=api_key)


# ============================================================
# SQL GENERATION
# ============================================================

def generate_sql(task):

    description = task["description"]
    table_info = task["table"]

    prompt = f"""
You are a database assistant.

Convert the user's request into exactly one SQL query.

User request:
{description}

Database schema:
{table_info}

Rules:
- Return ONLY one SQL query.
- Do not use markdown.
- Do not explain anything.
- Do not return multiple queries.
"""

    start = time.perf_counter()

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )

    latency_ms = (
        time.perf_counter() - start
    ) * 1000

    sql = response.text.strip()

    # Remove accidental markdown fences.
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

    return sql.strip(), latency_ms


# ============================================================
# SQL OPERATION
# ============================================================

def extract_operation(sql):

    match = re.match(
        r"\s*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)",
        sql,
        flags=re.IGNORECASE
    )

    if not match:
        return "UNKNOWN"

    return match.group(1).upper()


# ============================================================
# IDENTIFIER HELPERS
# ============================================================

def quote_identifier(identifier):

    return '"' + identifier.replace('"', '""') + '"'


def normalize_identifier(identifier):

    """
    Normalize an identifier for matching metadata variants.

    This is ONLY used to identify equivalent column-name
    representations. It does not change SQL semantics.
    """

    identifier = identifier.strip()

    identifier = identifier.replace(
        "`",
        ""
    )

    identifier = identifier.replace(
        '"',
        ""
    )

    identifier = identifier.lower()

    identifier = re.sub(
        r"[^a-z0-9]+",
        "",
        identifier
    )

    return identifier


# ============================================================
# REFERENCE IDENTIFIER EXTRACTION
# ============================================================

def extract_sql_identifiers(sql):

    """
    Extract identifiers appearing inside double quotes or
    backticks.

    Used only to discover column/table spelling variants
    used by the DBBench reference SQL.
    """

    identifiers = []

    patterns = [
        r'"([^"]+)"',
        r"`([^`]+)`"
    ]

    for pattern in patterns:

        identifiers.extend(
            re.findall(
                pattern,
                sql
            )
        )

    return identifiers


# ============================================================
# BUILD COLUMN COMPATIBILITY MAP
# ============================================================

def build_column_map(table):

    metadata_columns = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    mapping = {}

    for column in metadata_columns:

        mapping[
            normalize_identifier(column)
        ] = column

    return mapping


def find_metadata_column(
    identifier,
    column_map
):

    normalized = normalize_identifier(
        identifier
    )

    return column_map.get(
        normalized
    )


# ============================================================
# TEMPORARY DB CREATION
# ============================================================

def create_temp_database(table):

    conn = sqlite3.connect(":memory:")

    table_name = table["table_name"]

    columns = table["table_info"]["columns"]

    rows = table["table_info"]["rows"]

    column_names = [
        column["name"]
        for column in columns
    ]

    # --------------------------------------------------------
    # Create table using the exact DBBench metadata names.
    # --------------------------------------------------------

    column_definitions = ", ".join(
        f"{quote_identifier(name)} TEXT"
        for name in column_names
    )

    create_sql = (
        f"CREATE TABLE "
        f"{quote_identifier(table_name)} "
        f"({column_definitions})"
    )

    conn.execute(create_sql)

    # --------------------------------------------------------
    # Insert data.
    # --------------------------------------------------------

    placeholders = ", ".join(
        ["?"] * len(column_names)
    )

    insert_sql = (
        f"INSERT INTO "
        f"{quote_identifier(table_name)} "
        f"({', '.join(quote_identifier(c) for c in column_names)}) "
        f"VALUES ({placeholders})"
    )

    for row in rows:

        conn.execute(
            insert_sql,
            [
                None if value is None else str(value)
                for value in row
            ]
        )

    conn.commit()

    return conn


# ============================================================
# REFERENCE SQL COMPATIBILITY
# ============================================================

def build_compatibility_view(
    conn,
    table
):

    """
    Create a compatibility VIEW when DBBench metadata and
    reference SQL use spelling variants of the same identifier.

    Example:

        metadata:
            weeks_at_No_1

        reference SQL:
            weeks_at_No_1

    or other punctuation/case variants.

    The original table remains unchanged.
    """

    table_name = table["table_name"]

    columns = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    column_map = build_column_map(table)

    # --------------------------------------------------------
    # We do not alter the original table.
    #
    # SQLite cannot easily alias a column without creating
    # another object, so create a compatibility VIEW only
    # when a reference identifier differs from metadata.
    # --------------------------------------------------------

    return {
        "table_name": table_name,
        "columns": columns,
        "column_map": column_map
    }


# ============================================================
# RESULT NORMALIZATION
# ============================================================

def normalize_value(value):

    if value is None:
        return None

    if isinstance(value, float):

        if value.is_integer():
            return int(value)

        return round(
            value,
            10
        )

    return str(value).strip()


def normalize_result(rows):

    normalized = []

    for row in rows:

        normalized_row = tuple(
            normalize_value(value)
            for value in row
        )

        normalized.append(
            normalized_row
        )

    return normalized


# ============================================================
# SQL IDENTIFIER REPAIR
# ============================================================

def repair_sql_identifiers(
    sql,
    table
):

    """
    Repair only identifier spelling variants.

    Example:

        Metadata column:
            weeks_at_No_1

        Generated SQL:
            weeks at No. 1

    The repair maps the generated identifier to the actual
    metadata column when their normalized forms match.

    No values, predicates, operators, functions, or query
    structure are changed.
    """

    column_names = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    # --------------------------------------------------------
    # Build normalized lookup.
    # --------------------------------------------------------

    normalized_columns = {
        normalize_identifier(name): name
        for name in column_names
    }

    repaired_sql = sql

    # --------------------------------------------------------
    # Handle quoted identifiers.
    # --------------------------------------------------------

    quoted_patterns = [
        r"`([^`]+)`",
        r'"([^"]+)"'
    ]

    for pattern in quoted_patterns:

        matches = re.findall(
            pattern,
            repaired_sql
        )

        for identifier in matches:

            normalized = normalize_identifier(
                identifier
            )

            actual = normalized_columns.get(
                normalized
            )

            if actual is None:
                continue

            # Replace only if the spelling differs.
            if identifier != actual:

                repaired_sql = re.sub(
                    re.escape(
                        f"`{identifier}`"
                    ),
                    quote_identifier(actual),
                    repaired_sql
                )

                repaired_sql = re.sub(
                    re.escape(
                        f'"{identifier}"'
                    ),
                    quote_identifier(actual),
                    repaired_sql
                )

    return repaired_sql


# ============================================================
# READ-ONLY SQL EXECUTION
# ============================================================

def execute_query(
    conn,
    sql,
    table
):

    operation = extract_operation(
        sql
    )

    # --------------------------------------------------------
    # Safety restriction:
    # only SELECT is executed.
    # --------------------------------------------------------

    if operation != "SELECT":

        return {
            "executed": False,
            "success": False,
            "rows": None,
            "error": (
                "Non-SELECT SQL was not executed."
            )
        }

    # --------------------------------------------------------
    # Repair harmless identifier spelling variants.
    # --------------------------------------------------------

    executable_sql = repair_sql_identifiers(
        sql,
        table
    )

    try:

        cursor = conn.execute(
            executable_sql
        )

        rows = cursor.fetchall()

        normalized_rows = normalize_result(
            rows
        )

        return {
            "executed": True,
            "success": True,
            "rows": normalized_rows,
            "error": None,
            "executed_sql": executable_sql
        }

    except Exception as error:

        return {
            "executed": True,
            "success": False,
            "rows": None,
            "error": str(error),
            "executed_sql": executable_sql
        }


# ============================================================
# ANSWER-LEVEL EVALUATION
# ============================================================

def evaluate_sql(
    task,
    generated_sql
):

    reference_sql = task["sql"]

    conn = create_temp_database(
        task["table"]
    )

    try:

        reference_result = execute_query(
            conn,
            reference_sql,
            task["table"]
        )

        generated_result = execute_query(
            conn,
            generated_sql,
            task["table"]
        )

        # ----------------------------------------------------
        # Reference execution failure
        # ----------------------------------------------------

        if not reference_result["success"]:

            return {
                "status":
                    "REFERENCE_EXECUTION_ERROR",

                "correct":
                    None,

                "reference":
                    reference_result,

                "generated":
                    generated_result,

                "reason":
                    "Reference SQL could not be executed."
            }

        # ----------------------------------------------------
        # Generated SQL failure
        # ----------------------------------------------------

        if not generated_result["success"]:

            return {
                "status":
                    "GENERATED_EXECUTION_ERROR",

                "correct":
                    False,

                "reference":
                    reference_result,

                "generated":
                    generated_result,

                "reason":
                    "Generated SQL could not be executed."
            }

        # ----------------------------------------------------
        # Compare answer sets.
        # ----------------------------------------------------

        reference_rows = (
            reference_result["rows"]
        )

        generated_rows = (
            generated_result["rows"]
        )

        reference_sorted = sorted(
            reference_rows,
            key=lambda x: str(x)
        )

        generated_sorted = sorted(
            generated_rows,
            key=lambda x: str(x)
        )

        correct = (
            reference_sorted
            == generated_sorted
        )

        return {
            "status":
                "EVALUATED",

            "correct":
                correct,

            "reference":
                reference_result,

            "generated":
                generated_result,

            "reason":
                (
                    "Result sets match."
                    if correct
                    else
                    "Result sets differ."
                )
        }

    finally:

        conn.close()


# ============================================================
# NEUTRAL GUARDIAN INTENT
# ============================================================

def neutral_intent(
    reference_sql
):

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
# PREVIOUS RESULTS
# ============================================================

def load_previous_results():

    if not OUTPUT_FILE.exists():
        return []

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

        return []

    except Exception:

        print(
            "Warning: Could not read previous results."
        )

        return []


# ============================================================
# SAVE
# ============================================================

def save_results(
    results
):

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# GEMINI ERROR
# ============================================================

def is_temporary_gemini_error(
    error
):

    message = str(error).upper()

    keywords = [
        "429",
        "RESOURCE_EXHAUSTED",
        "QUOTA",
        "503",
        "UNAVAILABLE",
        "HIGH DEMAND",
        "RATE LIMIT"
    ]

    return any(
        keyword in message
        for keyword in keywords
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "GuardianAgent + DBBench LLM Pilot"
    )
    print("=" * 70)

    tasks = load_dbbench()

    previous_results = (
        load_previous_results()
    )

    completed_ids = {
        result.get("task_index")
        for result in previous_results
    }

    print()
    print(
        f"Total DBBench tasks : "
        f"{len(tasks)}"
    )

    print(
        f"Pilot tasks         : "
        f"{min(PILOT_SIZE, len(tasks))}"
    )

    print(
        f"Already completed   : "
        f"{len(completed_ids)}"
    )

    print(
        f"Gemini model        : "
        f"{MODEL_NAME}"
    )

    print(
        "SQL execution       : "
        "TEMPORARY IN-MEMORY DB ONLY"
    )

    print(
        "Guardian intent LLM : "
        "DISABLED"
    )

    print(
        "Guardian core       : "
        "FROZEN"
    )

    print()

    results = previous_results

    pilot_count = min(
        PILOT_SIZE,
        len(tasks)
    )

    new_llm_latencies = []
    new_guardian_latencies = []

    for index in range(
        pilot_count
    ):

        task_number = index + 1

        if index in completed_ids:

            print(
                f"[{task_number}/{pilot_count}] "
                "Already completed - skipping."
            )

            continue

        task = tasks[index]

        print("-" * 70)
        print(
            f"[{task_number}/{pilot_count}]"
        )
        print("-" * 70)

        print()
        print("USER REQUEST:")
        print(
            task["description"]
        )

        print()
        print("REFERENCE SQL:")
        print(
            task["sql"]
        )

        # ----------------------------------------------------
        # GEMINI
        # ----------------------------------------------------

        try:

            generated_sql, llm_latency = (
                generate_sql(task)
            )

        except Exception as error:

            print()
            print("GEMINI ERROR:")
            print(error)

            if is_temporary_gemini_error(
                error
            ):

                print()
                print(
                    "Temporary Gemini "
                    "service/quota problem detected."
                )

                print(
                    "Completed results "
                    "have been preserved."
                )

                break

            raise

        print()
        print("GENERATED SQL:")
        print(
            generated_sql
        )

        # ----------------------------------------------------
        # SQL ANSWER EVALUATION
        # ----------------------------------------------------

        sql_evaluation = evaluate_sql(
            task,
            generated_sql
        )

        print()
        print(
            "ANSWER-LEVEL SQL EVALUATION:"
        )

        status = (
            sql_evaluation["status"]
        )

        if status == "EVALUATED":

            if sql_evaluation["correct"]:

                print(
                    "SQL correctness : CORRECT"
                )

            else:

                print(
                    "SQL correctness : INCORRECT"
                )

        elif status == "REFERENCE_EXECUTION_ERROR":

            print(
                "SQL correctness : "
                "NOT EVALUATED"
            )

            print(
                "Reference SQL could "
                "not be executed."
            )

        else:

            print(
                "SQL correctness : "
                "INCORRECT"
            )

        print(
            "Status          : "
            f"{status}"
        )

        print(
            "Reason          : "
            f"{sql_evaluation['reason']}"
        )

        print()
        print(
            "REFERENCE RESULT:"
        )

        print(
            sql_evaluation[
                "reference"
            ]["rows"]
        )

        print()
        print(
            "GENERATED RESULT:"
        )

        print(
            sql_evaluation[
                "generated"
            ]["rows"]
        )

        # ----------------------------------------------------
        # GUARDIAN
        # ----------------------------------------------------

        intent = neutral_intent(
            task["sql"]
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

        decision = (
            guardian_result[
                "risk"
            ]["decision"]
        )

        risk_score = (
            guardian_result[
                "risk"
            ]["risk_score"]
        )

        risk_level = (
            guardian_result[
                "risk"
            ]["risk_level"]
        )

        print()
        print(
            "GUARDIAN RESULT:"
        )

        print(
            f"Decision       : "
            f"{decision}"
        )

        print(
            f"Risk score     : "
            f"{risk_score}"
        )

        print(
            f"Risk level     : "
            f"{risk_level}"
        )

        print()
        print(
            f"LLM latency     : "
            f"{llm_latency:.2f} ms"
        )

        print(
            f"Guardian latency: "
            f"{guardian_latency:.2f} ms"
        )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        result = {

            "task_index":
                index,

            "description":
                task["description"],

            "reference_sql":
                task["sql"],

            "generated_sql":
                generated_sql,

            "sql_evaluation":
                sql_evaluation,

            "reference_intent":
                intent,

            "guardian_result":
                guardian_result,

            "guardian_decision":
                decision,

            "risk_score":
                risk_score,

            "risk_level":
                risk_level,

            "llm_latency_ms":
                round(
                    llm_latency,
                    4
                ),

            "guardian_latency_ms":
                round(
                    guardian_latency,
                    4
                ),

            "sql_execution":
                "temporary_in_memory_only",

            "guardian_intent_llm":
                False
        }

        results.append(
            result
        )

        save_results(
            results
        )

        new_llm_latencies.append(
            llm_latency
        )

        new_guardian_latencies.append(
            guardian_latency
        )

        print()
        print(
            "Result saved."
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("=" * 70)
    print("PILOT SUMMARY")
    print("=" * 70)

    print()
    print(
        f"Completed tasks : "
        f"{len(results)}/{pilot_count}"
    )

    # --------------------------------------------------------
    # Guardian decisions
    # --------------------------------------------------------

    if results:

        decisions = {}

        for result in results:

            decision = (
                result[
                    "guardian_decision"
                ]
            )

            decisions[decision] = (
                decisions.get(
                    decision,
                    0
                ) + 1
            )

        print()
        print(
            "Guardian decisions:"
        )

        for decision in [
            "ALLOW",
            "CONFIRM",
            "BLOCK"
        ]:

            if decision in decisions:

                print(
                    f"  {decision:<10}: "
                    f"{decisions[decision]}"
                )

    # --------------------------------------------------------
    # SQL correctness
    # --------------------------------------------------------

    evaluated_results = [
        result
        for result in results
        if result[
            "sql_evaluation"
        ]["status"] == "EVALUATED"
    ]

    correct_results = [
        result
        for result in evaluated_results
        if result[
            "sql_evaluation"
        ]["correct"]
    ]

    reference_errors = [
        result
        for result in results
        if result[
            "sql_evaluation"
        ]["status"]
        == "REFERENCE_EXECUTION_ERROR"
    ]

    generated_errors = [
        result
        for result in results
        if result[
            "sql_evaluation"
        ]["status"]
        == "GENERATED_EXECUTION_ERROR"
    ]

    print()
    print(
        "SQL evaluation:"
    )

    print(
        f"  Evaluated          : "
        f"{len(evaluated_results)}"
    )

    print(
        f"  Correct            : "
        f"{len(correct_results)}"
    )

    print(
        f"  Reference errors   : "
        f"{len(reference_errors)}"
    )

    print(
        f"  Generated errors   : "
        f"{len(generated_errors)}"
    )

    if evaluated_results:

        accuracy = (
            100
            * len(correct_results)
            / len(evaluated_results)
        )

        print(
            f"  Answer accuracy    : "
            f"{accuracy:.2f}%"
        )

    # --------------------------------------------------------
    # New-case latency
    # --------------------------------------------------------

    if new_llm_latencies:

        print()
        print(
            "Average LLM latency:"
        )

        print(
            f"  {sum(new_llm_latencies) / len(new_llm_latencies):.2f} ms"
        )

    if new_guardian_latencies:

        print(
            "Average Guardian latency:"
        )

        print(
            f"  {sum(new_guardian_latencies) / len(new_guardian_latencies):.2f} ms"
        )

    # --------------------------------------------------------
    # Completion
    # --------------------------------------------------------

    if len(results) < pilot_count:

        print()
        print(
            "Pilot is incomplete because "
            "Gemini was unavailable."
        )

        print(
            "Run the same command later "
            "to resume."
        )

    else:

        print()
        print(
            "Pilot completed successfully."
        )

    print()
    print(
        f"Results file: "
        f"{OUTPUT_FILE}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()