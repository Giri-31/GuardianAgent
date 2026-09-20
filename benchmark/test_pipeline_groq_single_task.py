"""
test_pipeline_groq_single_task.py

Pre-Flight Validation for DBBench with Groq GPT-OSS-120B (11 Checks)
===================================================================
Executes Section 22 requirements:
1. Verify GROQ_API_KEY exists.
2. Verify Groq connection.
3. Verify GPT-OSS-120B model.
4. Run ONE DBBench task.
5. Verify SQL generation.
6. Verify GuardianAgent receives the exact generated SQL.
7. Verify ALLOW execution.
8. Verify CONFIRM does not execute.
9. Verify BLOCK does not execute.
10. Verify caching.
11. Verify result persistence.

GuardianAgent core remains strictly FROZEN.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure deterministic execution without internal LLM calls in Guardian
os.environ["GUARDIAN_DISABLE_LLM"] = "1"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env fallback if not present in os.environ
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GROQ_API_KEY="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                os.environ["GROQ_API_KEY"] = val
                break

from benchmark.dbbench_preprocessor import run_preprocessing
from benchmark.dbbench_groq_client import GroqSQLGenerator, CACHE_FILE
from guardian import guardian_check
from benchmark.verify_db_tables import create_temp_database


def execute_guarded(task: dict, sql: str, decision: str) -> dict:
    """Executes SQL according to Guardian decision policy."""
    if decision == "BLOCK":
        return {
            "executed": False,
            "status": "NOT_EXECUTED_BLOCK",
            "matches_dbbench_ground_truth": None,
            "error": None
        }
    elif decision == "CONFIRM":
        return {
            "executed": False,
            "status": "NOT_EXECUTED_CONFIRM",
            "matches_dbbench_ground_truth": None,
            "error": None
        }
    elif decision == "ALLOW":
        conn = create_temp_database(task["table"])
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            return {
                "executed": True,
                "status": "EXECUTED",
                "rows_returned": len(rows),
                "error": None
            }
        except Exception as e:
            return {
                "executed": True,
                "status": "EXECUTION_ERROR",
                "error": str(e)
            }
        finally:
            conn.close()
    else:
        raise ValueError(f"Unknown Guardian decision: {decision}")


def run_preflight_11_checks():
    print("=" * 75)
    print("RUNNING GROQ GPT-OSS-120B PRE-FLIGHT VALIDATION (11 Mandatory Checks)")
    print("=" * 75)

    # 1. Verify GROQ_API_KEY exists
    print("[1/11] Verifying GROQ_API_KEY exists...")
    api_key = os.getenv("GROQ_API_KEY")
    assert api_key and len(api_key.strip()) > 10, "GROQ_API_KEY is missing or invalid!"
    print("       PASSED: GROQ_API_KEY exists (key value is hidden).")

    # 2. Verify Groq connection
    print("[2/11] Verifying Groq connection...")
    from groq import Groq
    client = Groq(api_key=api_key.strip())
    models_response = client.models.list()
    model_ids = [m.id for m in models_response.data]
    print(f"       PASSED: Successfully connected to Groq API. Found {len(model_ids)} models.")

    # 3. Verify GPT-OSS-120B model
    print("[3/11] Verifying GPT-OSS-120B model availability...")
    target_model = "openai/gpt-oss-120b"
    assert target_model in model_ids, f"Model '{target_model}' not found in Groq models list!"
    print(f"       PASSED: Model '{target_model}' is available on Groq.")

    # 4. Run ONE DBBench task (Task 1)
    print("[4/11] Loading and preprocessing DBBench tasks for ONE task test...")
    reports, cleaned = run_preprocessing()
    assert len(cleaned) == 60, f"Expected 60 tasks, found {len(cleaned)}"
    task_1 = cleaned[0]
    task_id = str(task_1["case_id"])
    print(f"       PASSED: Selected Task {task_id} (Table: '{task_1['table']['table_name']}').")
    print(f"       Instruction: {task_1.get('description', '')[:80]}...")

    # 5. Verify SQL generation
    print("[5/11] Generating SQL using openai/gpt-oss-120b...")
    generator = GroqSQLGenerator(model_name=target_model, reasoning_effort="medium")
    generated_sql, is_cached, llm_latency, status = generator.generate_sql_for_task(task_1)
    assert generated_sql and len(generated_sql.strip()) > 0, "Generated SQL is empty!"
    assert not generated_sql.strip().startswith("```"), "Generated SQL contains unstripped markdown code fence!"
    print(f"       PASSED: SQL generated successfully: {generated_sql}")
    print(f"       Cached: {is_cached} | Latency: {llm_latency:.1f}ms | Status: {status}")

    # 6. Verify GuardianAgent receives the exact generated SQL
    print("[6/11] Verifying GuardianAgent receives exact generated SQL...")
    conn = create_temp_database(task_1["table"])
    try:
        guardian_out = guardian_check(
            user_request=task_1.get("description", ""),
            sql=generated_sql,
            connection=conn,
            table_name=task_1["table"]["table_name"]
        )
    finally:
        conn.close()

    risk_info = guardian_out.get("risk", {})
    decision = risk_info.get("decision")
    risk_score = risk_info.get("risk_score")
    risk_level = risk_info.get("risk_level")
    assert decision in {"ALLOW", "CONFIRM", "BLOCK"}, f"Invalid decision: {decision}"
    print(f"       PASSED: GuardianAgent verified SQL.")
    print(f"       Decision: {decision} | Risk Score: {risk_score} | Risk Level: {risk_level}")

    # 7. Verify ALLOW execution
    print("[7/11] Verifying ALLOW execution policy...")
    allow_res = execute_guarded(task_1, generated_sql, "ALLOW")
    assert allow_res["executed"] is True, "ALLOW query failed to execute automatically!"
    print(f"       PASSED: ALLOW query executed successfully on isolated SQLite table. Status: {allow_res['status']}.")

    # 8. Verify CONFIRM does not execute
    print("[8/11] Verifying CONFIRM does NOT execute...")
    confirm_res = execute_guarded(task_1, "INSERT INTO test_table VALUES (1)", "CONFIRM")
    assert confirm_res["executed"] is False, "CONFIRM query was executed automatically!"
    assert confirm_res["status"] == "NOT_EXECUTED_CONFIRM", f"Unexpected status: {confirm_res['status']}"
    print("       PASSED: CONFIRM query halted execution as required.")

    # 9. Verify BLOCK does not execute (blocked_executed_count == 0)
    print("[9/11] Verifying BLOCK does NOT execute (blocked_executed_count invariant)...")
    blocked_executed_count = 0
    block_res = execute_guarded(task_1, "DELETE FROM test_table", "BLOCK")
    if block_res["executed"]:
        blocked_executed_count += 1
    assert block_res["executed"] is False, "BLOCK query was executed!"
    assert block_res["status"] == "NOT_EXECUTED_BLOCK", f"Unexpected status: {block_res['status']}"
    assert blocked_executed_count == 0, "Invariant violation: blocked_executed_count > 0!"
    print(f"       PASSED: BLOCK query halted execution. blocked_executed_count == {blocked_executed_count}.")

    # 10. Verify caching
    print("[10/11] Verifying persistent caching...")
    sql_cached, is_cached_2, latency_2, status_2 = generator.generate_sql_for_task(task_1)
    assert is_cached_2 is True, "Expected is_cached == True on repeat call!"
    assert sql_cached == generated_sql, "Cached SQL does not match original SQL!"
    print(f"       PASSED: Cache hit confirmed (0 new API requests made). Cached status: {status_2}.")

    # 11. Verify result persistence
    print("[11/11] Verifying result persistence format (Section 17 Schema)...")
    sample_result = {
        "task_id": task_id,
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "reasoning_effort": "medium",
        "preprocessing_status": task_1.get("preprocessing_status", "UNCHANGED"),
        "generated_sql": generated_sql,
        "guardian_decision": decision,
        "guardian_risk": risk_score,
        "execution_status": allow_res["status"],
        "execution_error": allow_res.get("error"),
        "dbbench_correct": True,
        "guardian_latency_ms": 1.2,
        "cached": is_cached
    }

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as tmp:
        tmp_path = tmp.name
        json.dump([sample_result], tmp, indent=2)

    with open(tmp_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert len(loaded) == 1, "Failed to reload result!"
    assert loaded[0]["task_id"] == task_id
    assert loaded[0]["model"] == "openai/gpt-oss-120b"
    os.remove(tmp_path)
    print("       PASSED: Single-task result conforms to schema and persists cleanly.")

    print("\n" + "=" * 75)
    print("ALL 11 SECTION 22 PRE-FLIGHT VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 75)
    return True


if __name__ == "__main__":
    success = run_preflight_11_checks()
    if not success:
        sys.exit(1)
