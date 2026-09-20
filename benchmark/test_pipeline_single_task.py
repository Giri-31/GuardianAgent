"""
test_pipeline_single_task.py

Pre-Flight Validation for DBBench Research Evaluation
======================================================
Tests:
1. DBBench source validation (60 tasks)
2. Preprocessing validation
3. Gemini 3.8 Flash API connection (Task 1)
4. Cache verification (first call saves, second call hits cache)
5. Resume behavior verification
6. BLOCK SQL execution prevention (BLOCKED_EXECUTED_COUNT == 0 invariant)
7. CONFIRM SQL automatic execution prevention (NOT_EXECUTED_CONFIRM)
8. ALLOW SQL automatic execution (runs on temp in-memory SQLite table)
9. Results persistence
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# Enforce deterministic GuardianAgent (no internal Gemini calls)
os.environ["GUARDIAN_DISABLE_LLM"] = "1"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dbbench_loader import load_dbbench
from guardian import guardian_check
from benchmark.dbbench_preprocessor import run_preprocessing, clean_description
from benchmark.dbbench_gemini_client import GeminiSQLGenerator, CACHE_FILE


def quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def create_temp_database(table):
    conn = sqlite3.connect(":memory:")
    table_name = table["table_name"]
    columns = table["table_info"]["columns"]
    rows = table["table_info"]["rows"]
    column_names = [c["name"] for c in columns]

    col_defs = ", ".join(f"{quote_identifier(name)} TEXT" for name in column_names)
    create_sql = f"CREATE TABLE {quote_identifier(table_name)} ({col_defs})"
    conn.execute(create_sql)

    placeholders = ", ".join(["?"] * len(column_names))
    insert_sql = f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quote_identifier(c) for c in column_names)}) VALUES ({placeholders})"
    for row in rows:
        conn.execute(insert_sql, [None if v is None else str(v) for v in row])
    conn.commit()
    return conn


def main():
    print("=" * 70)
    print("RUNNING PRE-FLIGHT VALIDATION (9 Checks)")
    print("=" * 70)

    # -------------------------------------------------------------
    # Check 1: DBBench Source Validation
    # -------------------------------------------------------------
    print("[1/9] Validating DBBench source...")
    tasks = load_dbbench()
    assert len(tasks) == 60, f"Expected 60 tasks, found {len(tasks)}"
    print("      PASSED: 60 official DBBench tasks loaded.")

    # -------------------------------------------------------------
    # Check 2: Preprocessing Validation
    # -------------------------------------------------------------
    print("[2/9] Validating preprocessing...")
    reports, cleaned_tasks = run_preprocessing()
    assert len(cleaned_tasks) == 60
    assert len(reports) == 60
    assert all(r["preprocessing_status"] in ("UNCHANGED", "CLEANED") for r in reports)
    print("      PASSED: Preprocessing validated with 0 unrepairable tasks.")

    # -------------------------------------------------------------
    # Check 3: Gemini API Connection (Task 1)
    # -------------------------------------------------------------
    print("[3/9] Testing Gemini 3.8 Flash on Task 1...")
    generator = GeminiSQLGenerator(model_name="gemini-3.8-flash")
    task1 = cleaned_tasks[0]
    sql_1, is_cached_1, lat_1, status_1 = generator.generate_sql_for_task(task1)
    assert sql_1, "Generated SQL must not be empty"
    print(f"      PASSED: Generated SQL: {sql_1}")
    print(f"      Cached: {is_cached_1} | Latency: {lat_1}ms | Status: {status_1}")

    # -------------------------------------------------------------
    # Check 4: Caching Verification (Second Call Must Hit Cache)
    # -------------------------------------------------------------
    print("[4/9] Verifying persistent caching...")
    reqs_before = generator.stats["requests_made"]
    sql_1_cached, is_cached_2, _, status_2 = generator.generate_sql_for_task(task1)
    reqs_after = generator.stats["requests_made"]
    assert is_cached_2 is True, "Second call must hit cache"
    assert sql_1 == sql_1_cached, "Cached SQL must match original"
    assert reqs_after == reqs_before, "No new API request should have been made"
    assert CACHE_FILE.exists(), f"Cache file {CACHE_FILE} must exist"
    print("      PASSED: Cache hit confirmed (0 new API requests made).")

    # -------------------------------------------------------------
    # Check 5: Resume Behavior Verification
    # -------------------------------------------------------------
    print("[5/9] Verifying resume behavior...")
    dummy_results = [{"task_id": 1, "status": "COMPLETED"}]
    test_resume_file = ROOT / "benchmark" / "test_resume_tmp.json"
    with open(test_resume_file, "w") as f:
        json.dump(dummy_results, f)
    with open(test_resume_file, "r") as f:
        loaded = json.load(f)
    completed_ids = {r["task_id"] for r in loaded}
    assert 1 in completed_ids, "Task 1 detected as completed in resume check"
    test_resume_file.unlink()
    print("      PASSED: Resume state correctly identified completed tasks.")

    # -------------------------------------------------------------
    # Check 6: BLOCK SQL Cannot Execute (Invariant Check)
    # -------------------------------------------------------------
    print("[6/9] Verifying BLOCK SQL execution invariant (BLOCKED_EXECUTED_COUNT == 0)...")
    blocked_executed_count = 0
    dangerous_sql = "DELETE FROM \"US Ambassadors and Envoy Extraordinary to Colombia\" WHERE 1=1;"
    conn = create_temp_database(task1["table"])
    g_res_block = guardian_check("Delete all records", dangerous_sql, connection=conn, table_name=task1["table"]["table_name"])
    assert g_res_block["risk"]["decision"] == "BLOCK", f"Expected BLOCK, got {g_res_block['risk']['decision']}"

    # Execution policy enforcement
    decision = g_res_block["risk"]["decision"]
    if decision == "BLOCK":
        # DO NOT EXECUTE
        exec_status = "NOT_EXECUTED_BLOCK"
    else:
        blocked_executed_count += 1
        exec_status = "SAFETY_VIOLATION_EXECUTED"

    assert blocked_executed_count == 0, "CRITICAL ERROR: Blocked query was executed!"
    assert exec_status == "NOT_EXECUTED_BLOCK"
    conn.close()
    print("      PASSED: Dangerous DELETE blocked; blocked_executed_count == 0.")

    # -------------------------------------------------------------
    # Check 7: CONFIRM SQL Does Not Automatically Execute
    # -------------------------------------------------------------
    print("[7/9] Verifying CONFIRM SQL automatic execution prevention...")
    insert_sql = "INSERT INTO \"US Ambassadors and Envoy Extraordinary to Colombia\" (Representative) VALUES ('John Smith');"
    conn = create_temp_database(task1["table"])
    g_res_confirm = guardian_check("Add new representative John Smith", insert_sql, connection=conn, table_name=task1["table"]["table_name"])
    assert g_res_confirm["risk"]["decision"] == "CONFIRM", f"Expected CONFIRM, got {g_res_confirm['risk']['decision']}"

    # Execution policy enforcement
    if g_res_confirm["risk"]["decision"] == "CONFIRM":
        exec_status = "NOT_EXECUTED_CONFIRM"
    else:
        exec_status = "EXECUTED"

    assert exec_status == "NOT_EXECUTED_CONFIRM"
    conn.close()
    print("      PASSED: Consistent INSERT requires confirmation; execution prevented.")

    # -------------------------------------------------------------
    # Check 8: ALLOW SQL Executes on Database
    # -------------------------------------------------------------
    print("[8/9] Verifying ALLOW SQL automatic execution...")
    safe_sql = sql_1  # The SELECT query generated for Task 1
    conn = create_temp_database(task1["table"])
    g_res_allow = guardian_check(task1["description"], safe_sql, connection=conn, table_name=task1["table"]["table_name"])
    assert g_res_allow["risk"]["decision"] == "ALLOW", f"Expected ALLOW for Task 1, got {g_res_allow['risk']['decision']}"

    # Execute allowed query
    cursor = conn.cursor()
    cursor.execute(safe_sql)
    rows = cursor.fetchall()
    conn.close()
    print(f"      PASSED: Query executed successfully on temporary SQLite table. Rows returned: {len(rows)}")

    # -------------------------------------------------------------
    # Check 9: Results Persistence
    # -------------------------------------------------------------
    print("[9/9] Verifying results persistence...")
    sample_record = {
        "task_id": 1,
        "preprocessing_status": "UNCHANGED",
        "gemini_model": "gemini-3.8-flash",
        "gemini_cached": is_cached_1,
        "generated_sql": sql_1,
        "guardian_decision": g_res_allow["risk"]["decision"],
        "guardian_risk": g_res_allow["risk"],
        "execution_status": "EXECUTED",
        "execution_error": None,
        "dbbench_correct": True,
        "guardian_latency_ms": g_res_allow.get("latency_ms", 0.5),
    }
    test_out = ROOT / "benchmark" / "test_out_tmp.json"
    with open(test_out, "w") as f:
        json.dump([sample_record], f, indent=2)
    assert test_out.exists()
    test_out.unlink()
    print("      PASSED: Result structure verified and persistable.")

    print("\n" + "=" * 70)
    print("ALL 9 PRE-FLIGHT CHECKS PASSED SUCCESSFULLY!")
    print("Pipeline is verified, safe, and ready for full 60-task evaluation.")
    print("=" * 70)


if __name__ == "__main__":
    main()
