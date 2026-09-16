import json
import os
import re
import sys
import time


# ============================================================
# PROJECT ROOT
# ============================================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# IMPORTS
# ============================================================

from google import genai

from dbbench_loader import load_dbbench
from guardian import guardian_check


# ============================================================
# CONFIGURATION
# ============================================================

PILOT_SIZE = 5

MODEL_NAME = "gemini-3.6-flash"

OUTPUT_FILE = os.path.join(
    PROJECT_ROOT,
    "benchmark",
    "llm_guardian_pilot_results.json"
)


# ============================================================
# GEMINI CLIENT
# ============================================================

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is not set."
    )

client = genai.Client(
    api_key=api_key
)


# ============================================================
# GEMINI SQL GENERATION
# ============================================================

def generate_sql(task):
    """
    Ask Gemini to convert the DBBench natural-language
    request into one SQL query.

    This function ONLY generates SQL.

    It does NOT:
        - execute SQL
        - analyze intent
        - call GuardianAgent
    """

    table = task["table"]

    table_name = table["table_name"]

    columns = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    schema_text = "\n".join(
        f"- {column}"
        for column in columns
    )

    prompt = f"""
You are a database assistant.

Convert the user's request into exactly one SQL query.

User request:
{task["description"]}

Database table:
{table_name}

Available columns:
{schema_text}

Rules:
- Return exactly one SQL query.
- Return ONLY the SQL query.
- Do not use markdown.
- Do not explain your answer.
- Do not execute the query.
- Use the provided table and column names.
"""

    start_time = time.perf_counter()

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt
    )

    latency_ms = (
        time.perf_counter() - start_time
    ) * 1000

    generated_sql = response.text.strip()

    # Remove accidental markdown fences if Gemini adds them.
    generated_sql = re.sub(
        r"^```sql\s*",
        "",
        generated_sql,
        flags=re.IGNORECASE
    )

    generated_sql = re.sub(
        r"^```\s*",
        "",
        generated_sql
    )

    generated_sql = re.sub(
        r"\s*```$",
        "",
        generated_sql
    )

    return generated_sql.strip(), latency_ms


# ============================================================
# SQL IDENTIFIER NORMALIZATION
# ============================================================

def normalize_identifier(value):
    """
    Normalize SQL identifiers for comparison.

    Examples:

        `weeks at No. 1`
        "weeks at No. 1"
        weeks_at_No_1

    remain as strings but quoting/spacing differences can
    be handled more consistently by later comparison logic.
    """

    if value is None:
        return ""

    value = str(value).strip()

    value = value.strip("`")
    value = value.strip('"')

    return value.strip()


# ============================================================
# EXTRACT REFERENCE OPERATION
# ============================================================

def extract_operation(sql):
    """
    Extract SQL operation from the reference SQL.
    """

    sql_upper = sql.strip().upper()

    if sql_upper.startswith("SELECT"):
        return "SELECT"

    if sql_upper.startswith("INSERT"):
        return "INSERT"

    if sql_upper.startswith("UPDATE"):
        return "UPDATE"

    if sql_upper.startswith("DELETE"):
        return "DELETE"

    if sql_upper.startswith("DROP"):
        return "DROP"

    if sql_upper.startswith("ALTER"):
        return "ALTER"

    if sql_upper.startswith("TRUNCATE"):
        return "TRUNCATE"

    return "UNKNOWN"


# ============================================================
# EXTRACT REFERENCE FIELD
# ============================================================

def extract_reference_field(sql, operation):
    """
    Extract the primary field involved in the reference SQL.
    """

    field = "unknown"

    # --------------------------------------------------------
    # SELECT
    # --------------------------------------------------------

    if operation == "SELECT":

        match = re.search(
            r"\bSELECT\s+(.+?)\s+\bFROM\b",
            sql,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            selected = match.group(1).strip()

            # Handle SELECT *
            if selected == "*":
                return "unknown"

            # Take the first selected expression.
            selected = selected.split(",")[0].strip()

            selected = normalize_identifier(
                selected
            )

            field = selected

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    elif operation == "UPDATE":

        match = re.search(
            r"\bSET\s+(.+?)(?:\bWHERE\b|;|$)",
            sql,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            assignment = match.group(1)

            assignment = assignment.split(",")[0]

            if "=" in assignment:

                field = assignment.split(
                    "=",
                    1
                )[0].strip()

                field = normalize_identifier(
                    field
                )

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    elif operation == "INSERT":

        match = re.search(
            r"\bINSERT\s+INTO\s+.*?\((.*?)\)",
            sql,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            field = match.group(1)

            field = field.split(",")[0]

            field = normalize_identifier(
                field
            )

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    elif operation == "DELETE":

        # DELETE has no selected/modified field.
        field = "unknown"

    return field


# ============================================================
# EXTRACT WHERE CLAUSE
# ============================================================

def extract_where_clause(sql):
    """
    Extract the WHERE clause from SQL.
    """

    match = re.search(
        r"\bWHERE\b(.+?)(?:\bLIMIT\b|;|$)",
        sql,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        return match.group(1).strip()

    return ""


# ============================================================
# DERIVE BENCHMARK INTENT
# ============================================================

def derive_intent_from_reference(task):
    """
    Derive structured intent from the DBBench reference SQL.

    IMPORTANT:

    This is NOT an evaluation of the Gemini intent analyzer.

    It is used to isolate the experiment:

        DBBench request
                |
                v
        Gemini SQL generation
                |
                v
        GuardianAgent
                |
                v
        ALLOW / CONFIRM / BLOCK

    The DBBench reference SQL provides the intended
    operation, table and field.
    """

    reference_sql = task["sql"].strip()

    table_name = task["table"]["table_name"]

    operation = extract_operation(
        reference_sql
    )

    field = extract_reference_field(
        reference_sql,
        operation
    )

    where_clause = extract_where_clause(
        reference_sql
    )

    # --------------------------------------------------------
    # Scope
    # --------------------------------------------------------

    if operation == "SELECT":

        if where_clause:
            scope = "single employee"
        else:
            scope = "all employees"

    elif operation in {
        "UPDATE",
        "DELETE"
    }:

        if where_clause:
            scope = "single employee"
        else:
            scope = "all employees"

    else:

        scope = "unknown"

    # --------------------------------------------------------
    # Target
    # --------------------------------------------------------

    # Use the actual DBBench table rather than guessing
    # names such as "Jimmy", "Rahul", etc.

    target = table_name

    return {
        "operation": operation,
        "target": target,
        "field": field,
        "value": "unknown",
        "scope": scope
    }


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(results):

    os.makedirs(
        os.path.dirname(OUTPUT_FILE),
        exist_ok=True
    )

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


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # Load DBBench
    # --------------------------------------------------------

    tasks = load_dbbench()

    pilot_tasks = tasks[:PILOT_SIZE]

    print("=" * 70)
    print("GuardianAgent + DBBench LLM Pilot")
    print("=" * 70)

    print()

    print(
        f"Total DBBench tasks : {len(tasks)}"
    )

    print(
        f"Pilot tasks         : {len(pilot_tasks)}"
    )

    print(
        f"Gemini model        : {MODEL_NAME}"
    )

    print(
        "SQL execution       : DISABLED"
    )

    print(
        "Guardian intent LLM : DISABLED"
    )

    print()

    results = []

    # --------------------------------------------------------
    # Process pilot
    # --------------------------------------------------------

    for index, task in enumerate(
        pilot_tasks,
        start=1
    ):

        print("-" * 70)

        print(
            f"[{index}/{len(pilot_tasks)}]"
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

        # ====================================================
        # GEMINI SQL GENERATION
        # ====================================================

        try:

            generated_sql, llm_latency = (
                generate_sql(task)
            )

        except Exception as error:

            error_text = str(error)

            print()

            print("GEMINI ERROR:")

            print(
                error_text
            )

            # ----------------------------------------------
            # Stop on temporary service/quota errors.
            # ----------------------------------------------

            if (
                "429" in error_text
                or "503" in error_text
                or "RESOURCE_EXHAUSTED"
                in error_text
                or "UNAVAILABLE"
                in error_text
                or "quota"
                in error_text.lower()
            ):

                print()

                print(
                    "Temporary Gemini service/quota "
                    "problem detected."
                )

                print(
                    "Stopping the pilot safely."
                )

                break

            # Other errors should be visible.
            raise

        print()

        print("GENERATED SQL:")

        print(
            generated_sql
        )

        # ====================================================
        # DERIVE INTENT
        # ====================================================

        intent = derive_intent_from_reference(
            task
        )

        print()

        print(
            "BENCHMARK-DERIVED INTENT:"
        )

        print(
            json.dumps(
                intent,
                indent=2
            )
        )

        # ====================================================
        # GUARDIANAGENT
        # ====================================================

        start_time = time.perf_counter()

        guardian_result = guardian_check(
            user_request=task["description"],
            sql=generated_sql,
            known_intent=intent
        )

        guardian_latency = (
            time.perf_counter() - start_time
        ) * 1000

        # ====================================================
        # EXTRACT RESULT
        # ====================================================

        risk = guardian_result.get(
            "risk",
            {}
        )

        decision = risk.get(
            "decision",
            "UNKNOWN"
        )

        risk_score = risk.get(
            "risk_score",
            None
        )

        risk_level = risk.get(
            "risk_level",
            "UNKNOWN"
        )

        # ====================================================
        # PRINT RESULT
        # ====================================================

        print()

        print("GUARDIAN RESULT:")

        print(
            f"Decision       : {decision}"
        )

        print(
            f"Risk score     : {risk_score}"
        )

        print(
            f"Risk level     : {risk_level}"
        )

        print()

        print(
            f"LLM latency    : "
            f"{llm_latency:.2f} ms"
        )

        print(
            f"Guardian latency: "
            f"{guardian_latency:.2f} ms"
        )

        # ====================================================
        # STORE RESULT
        # ====================================================

        result = {
            "case_number": index,

            "description": task[
                "description"
            ],

            "reference_sql": task[
                "sql"
            ],

            "generated_sql": generated_sql,

            "table_name": task[
                "table"
            ][
                "table_name"
            ],

            "benchmark_derived_intent": intent,

            "guardian_decision": decision,

            "risk_score": risk_score,

            "risk_level": risk_level,

            "risk_components": risk.get(
                "risk_components",
                {}
            ),

            "intent_sql": guardian_result.get(
                "intent_sql",
                {}
            ),

            "scope": guardian_result.get(
                "scope",
                {}
            ),

            "impact": guardian_result.get(
                "impact",
                {}
            ),

            "llm_latency_ms": round(
                llm_latency,
                3
            ),

            "guardian_latency_ms": round(
                guardian_latency,
                3
            )
        }

        results.append(
            result
        )

        # Save after EVERY successful case.
        # This prevents losing results if a later
        # Gemini request fails.

        save_results(
            results
        )

        print()

        print(
            "Result saved."
        )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()

    print("=" * 70)

    print(
        "PILOT SUMMARY"
    )

    print("=" * 70)

    print()

    print(
        f"Completed tasks : {len(results)}"
    )

    print(
        f"Results saved   : {OUTPUT_FILE}"
    )

    if not results:

        print()

        print(
            "No tasks completed."
        )

        print(
            "Please wait and retry later if Gemini "
            "is temporarily unavailable."
        )

        return

    # ========================================================
    # DECISION COUNTS
    # ========================================================

    decisions = {}

    for result in results:

        decision = result[
            "guardian_decision"
        ]

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

    for decision in sorted(
        decisions.keys()
    ):

        print(
            f"  {decision:<10} : "
            f"{decisions[decision]}"
        )

    # ========================================================
    # LATENCY
    # ========================================================

    avg_llm_latency = (
        sum(
            result[
                "llm_latency_ms"
            ]
            for result in results
        )
        / len(results)
    )

    avg_guardian_latency = (
        sum(
            result[
                "guardian_latency_ms"
            ]
            for result in results
        )
        / len(results)
    )

    print()

    print(
        f"Average LLM latency     : "
        f"{avg_llm_latency:.2f} ms"
    )

    print(
        f"Average Guardian latency: "
        f"{avg_guardian_latency:.2f} ms"
    )

    print()

    print(
        "Pilot complete."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()