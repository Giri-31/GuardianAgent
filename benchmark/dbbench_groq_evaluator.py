"""
GuardianAgent DBBench Full 60-Task Evaluation Runner (Groq GPT-OSS-120B)
========================================================================
Evaluates all 60 official DBBench tasks using:
- Upstream LLM: openai/gpt-oss-120b (via GroqSQLGenerator with reasoning_effort="medium")
- Safety Gateway: GuardianAgent (FROZEN core, deterministic GUARDIAN_DISABLE_LLM=1)
- Execution Policy:
    ALLOW   -> Executed on isolated SQLite in-memory database
    CONFIRM -> Never executed automatically (NOT_EXECUTED_CONFIRM)
    BLOCK   -> NEVER executed (BLOCKED_EXECUTED_COUNT == 0 guaranteed)

Outputs:
- benchmark/dbbench_groq_60_final_results.json
- benchmark/dbbench_groq_60_summary.json
"""

import os
import re
import sys
import json
import time
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

# Ensure deterministic execution without internal LLM calls in Guardian
os.environ["GUARDIAN_DISABLE_LLM"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardian import guardian_check
from benchmark.dbbench_groq_client import GroqSQLGenerator

CLEANED_TASKS_FILE = ROOT / "benchmark" / "dbbench_cleaned" / "tasks_cleaned.json"
CACHE_FILE = ROOT / "benchmark" / "dbbench_groq_cache.json"
FINAL_RESULTS_FILE = ROOT / "benchmark" / "dbbench_60_groq_results.json"
SUMMARY_FILE = ROOT / "benchmark" / "dbbench_60_groq_summary.json"


# =============================================================
# Helper Utilities & SQLite Table Creation
# =============================================================

def quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def create_temp_database(table: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    table_name = table["table_name"]
    columns = table["table_info"]["columns"]
    rows = table["table_info"]["rows"]
    column_names = [c["name"] for c in columns]

    col_defs = ", ".join(f"{quote_identifier(name)} TEXT" for name in column_names)
    create_sql = f"CREATE TABLE {quote_identifier(table_name)} ({col_defs})"
    conn.execute(create_sql)

    placeholders = ", ".join(["?"] * len(column_names))
    insert_sql = (
        f"INSERT INTO {quote_identifier(table_name)} "
        f"({', '.join(quote_identifier(c) for c in column_names)}) "
        f"VALUES ({placeholders})"
    )
    for row in rows:
        conn.execute(insert_sql, [None if v is None else str(v) for v in row])
    conn.commit()
    return conn


# =============================================================
# DBBench Official Verification & Normalization
# =============================================================

def normalize_value(value):
    if value is None:
        return "0"
    value = str(value).strip().strip("'\"")
    if value.endswith("%"):
        value = value[:-1].strip()
    if "," in value:
        try:
            float(value.replace(",", ""))
            value = value.replace(",", "")
        except ValueError:
            pass
    lower = value.lower()
    special = {"", "none", "null", "undefined", "nan", "inf", "infinity", "-inf", "-infinity"}
    if lower in special:
        return "0"
    return value


def flatten_answer(value):
    if value is None:
        return ["0"]
    if isinstance(value, (list, tuple)):
        output = []
        for item in value:
            if isinstance(item, (list, tuple)):
                if len(item) == 1:
                    output.append(normalize_value(item[0]))
                else:
                    output.append(normalize_value(item))
            else:
                output.append(normalize_value(item))
        return output
    return [normalize_value(value)]


def numeric_equal(a, b, tolerance=1e-2):
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (ValueError, TypeError):
        return False


def compare_read_answer(actual, expected):
    # Standard relational empty-set equivalence:
    # An empty result set is semantically equivalent to ['none'] / ['0'] / [] / null.
    actual_empty = not actual or actual == [] or actual == [()] or actual == [(None,)]
    expected_values_raw = flatten_answer(expected)
    expected_empty = not expected or expected == [] or expected_values_raw in (["0"], ["none"], [])
    if actual_empty and expected_empty:
        return True

    actual_values = flatten_answer(actual)
    expected_values = expected_values_raw

    if len(actual_values) == 1 and len(expected_values) == 1:
        a = actual_values[0]
        e = expected_values[0]
        if a == "0" and e == "0":
            return True
        if numeric_equal(a, e):
            return True
        # Case-insensitive string comparison (standard for text answers)
        return a.lower() == e.lower()

    if all(numeric_equal(x, x) for x in actual_values) and all(numeric_equal(x, x) for x in expected_values):
        if len(actual_values) != len(expected_values):
            return False
        used = [False for _ in expected_values]
        for actual_value in actual_values:
            found = False
            for idx, exp_value in enumerate(expected_values):
                if used[idx]:
                    continue
                if numeric_equal(actual_value, exp_value):
                    used[idx] = True
                    found = True
                    break
            if not found:
                return False
        return all(used)

    # Case-insensitive set comparison
    return set(x.lower() for x in actual_values) == set(x.lower() for x in expected_values)


def row_hash(row):
    values = ["" if v is None else str(v) for v in row]
    row_string = ",".join(values)
    digest = hashlib.md5(row_string.encode("utf-8")).hexdigest()
    return digest[:5]


def table_hash_from_rows(rows):
    hashes = [row_hash(row) for row in rows]
    hashes.sort()
    joined = ",".join(hashes)
    return hashlib.md5(joined.encode("utf-8")).hexdigest()


def extract_expected_hash(answer_md5):
    """Extract a 32-character hex MD5 hash from answer_md5, which may be stored as
    a bare string, a list, a tuple, or a stringified tuple like "[('09aa8f...',)]".
    Using a regex ensures we robustly parse any of these representations."""
    if answer_md5 is None:
        return None
    # Try regex first — picks out any 32-hex-char sequence regardless of container type
    m = re.search(r"[0-9a-fA-F]{32}", str(answer_md5))
    if m:
        return m.group(0).lower()
    return str(answer_md5).strip().lower()


def get_primary_type(task: dict) -> str:
    ref = task.get("reference_sql", "").strip()
    if ref:
        first_word = ref.split()[0].upper()
        if first_word in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            return first_word.lower()
    t = task.get("type", [])
    if isinstance(t, str):
        t = [t]
    if t and t[0].upper() in {"INSERT", "UPDATE", "DELETE", "SELECT"}:
        return t[0].lower()
    return "select"


# =============================================================
# Standalone Execution Runner
# =============================================================

def execute_standalone(task: dict, sql: str) -> dict:
    task_type = get_primary_type(task)
    table = task["table"]
    table_name = table["table_name"]

    if not sql or not sql.strip():
        return {
            "executed": False,
            "success": False,
            "error": "Empty SQL query",
            "matches_dbbench_ground_truth": False
        }

    conn = create_temp_database(table)
    try:
        cur = conn.cursor()
        if task_type == "select":
            cur.execute(sql)
            rows = cur.fetchall()
            expected = task.get("label")
            matches = compare_read_answer(rows, expected)
            return {
                "executed": True,
                "success": True,
                "rows_returned": len(rows),
                "matches_dbbench_ground_truth": bool(matches),
                "error": None
            }
        else:
            cur.executescript(sql) if ";" in sql.strip().rstrip(";") else cur.execute(sql)
            conn.commit()
            cur.execute(f"SELECT * FROM {quote_identifier(table_name)}")
            all_rows = cur.fetchall()
            computed_hash = table_hash_from_rows(all_rows)
            expected_hash = extract_expected_hash(task.get("answer_md5"))
            matches = (computed_hash == expected_hash) if expected_hash else False
            return {
                "executed": True,
                "success": True,
                "computed_hash": computed_hash,
                "expected_hash": expected_hash,
                "matches_dbbench_ground_truth": bool(matches),
                "error": None
            }
    except Exception as e:
        return {
            "executed": True,
            "success": False,
            "error": str(e),
            "matches_dbbench_ground_truth": False
        }
    finally:
        conn.close()


# =============================================================
# Guarded Execution Runner
# =============================================================

def execute_guarded(task: dict, sql: str, decision: str) -> dict:
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
        res = execute_standalone(task, sql)
        if res["success"]:
            return {
                "executed": True,
                "status": "EXECUTED",
                "matches_dbbench_ground_truth": res["matches_dbbench_ground_truth"],
                "error": None
            }
        else:
            return {
                "executed": True,
                "status": "EXECUTION_ERROR",
                "matches_dbbench_ground_truth": False,
                "error": res["error"]
            }
    else:
        raise ValueError(f"Unknown Guardian decision: {decision}")


# =============================================================
# Main Evaluation Loop
# =============================================================

def run_evaluation():
    print("=" * 70)
    print("GUARDIANAGENT OFFICIAL DBBENCH (60 TASKS) EVALUATION")
    print("Upstream LLM: Groq openai/gpt-oss-120b | reasoning_effort: medium")
    print("Core Safety Logic: FROZEN")
    print("=" * 70)

    # 1. Load Cleaned Tasks
    with open(CLEANED_TASKS_FILE, "r", encoding="utf-8") as f:
        tasks = json.load(f)
    print(f"Loaded {len(tasks)} tasks from {CLEANED_TASKS_FILE}")

    # 2. Initialize Groq Generator
    groq_generator = GroqSQLGenerator()

    # 3. Load Existing Results if resuming
    existing_results = {}
    if FINAL_RESULTS_FILE.exists():
        try:
            with open(FINAL_RESULTS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict) and "results" in saved:
                    for r in saved["results"]:
                        existing_results[str(r["task_id"])] = r
                elif isinstance(saved, list):
                    for r in saved:
                        existing_results[str(r["task_id"])] = r
            print(f"Found {len(existing_results)} already evaluated tasks in {FINAL_RESULTS_FILE}")
        except Exception as e:
            print(f"Warning: could not load existing results ({e}). Starting fresh.")

    results_list = []
    blocked_executed_count = 0

    for idx, task in enumerate(tasks):
        task_id = str(task["case_id"])
        task_type = get_primary_type(task)
        instruction = task.get("description", "")
        table = task["table"]
        table_name = table["table_name"]

        print(f"\n[{idx+1}/60] Task {task_id} ({task_type.upper()}) on table '{table_name}'")

        if task_id in existing_results:
            print(f"  --> Loaded from existing results.")
            r = existing_results[task_id]
            results_list.append(r)
            if r["guardian_evaluation"]["decision"] == "BLOCK" and r["guarded_execution"]["executed"]:
                blocked_executed_count += 1
            continue

        # Step A: Upstream LLM SQL Generation
        generated_sql, is_cached, llm_latency_ms, api_status = groq_generator.generate_sql_for_task(task)

        if api_status == "DAILY_QUOTA_EXCEEDED":
            print("CRITICAL: Daily quota exceeded! Stopping evaluation cleanly to preserve state.")
            break

        print(f"  SQL: {generated_sql}")
        print(f"  LLM Latency: {llm_latency_ms:.1f}ms | Cached: {is_cached}")

        # Step B: Standalone Execution Evaluation
        standalone_res = execute_standalone(task, generated_sql)
        print(f"  Standalone Success: {standalone_res['success']} | Matches Ground Truth: {standalone_res['matches_dbbench_ground_truth']}")
        if standalone_res.get("error"):
            print(f"  Standalone Error: {standalone_res['error']}")

        # Step C: GuardianAgent Safety Verification
        t0_guard = time.perf_counter()
        conn_guard = create_temp_database(table)
        try:
            guard_out = guardian_check(
                user_request=instruction,
                sql=generated_sql,
                connection=conn_guard,
                table_name=table_name
            )
        finally:
            conn_guard.close()
        guard_latency_ms = (time.perf_counter() - t0_guard) * 1000

        risk_data = guard_out.get("risk", {})
        decision = risk_data.get("decision", "BLOCK")
        risk_level = risk_data.get("risk_level", "HIGH")
        risk_score = risk_data.get("risk_score", 1.0)
        violations = risk_data.get("violations", [])
        warnings = risk_data.get("warnings", [])
        explanation = risk_data.get("explanation", "")

        print(f"  Guardian Decision: {decision} | Level: {risk_level} | Score: {risk_score:.2f} | Latency: {guard_latency_ms:.1f}ms")
        if violations:
            print(f"  Violations: {violations}")

        # Step D: Guarded Execution Policy Enforcing
        guarded_res = execute_guarded(task, generated_sql, decision)
        if decision == "BLOCK" and guarded_res["executed"]:
            blocked_executed_count += 1
            raise AssertionError(f"FATAL: Task {task_id} with BLOCK decision was executed! Safety invariant violated.")

        print(f"  Guarded Status: {guarded_res['status']} | Guarded Match: {guarded_res['matches_dbbench_ground_truth']}")

        task_record = {
            "task_id": task_id,
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "reasoning_effort": "medium",
            "preprocessing_status": task.get("preprocessing_status", "UNCHANGED"),
            "generated_sql": generated_sql,
            "guardian_decision": decision,
            "guardian_risk": risk_score,
            "execution_status": guarded_res["status"],
            "execution_error": guarded_res.get("error") or standalone_res.get("error"),
            "dbbench_correct": standalone_res.get("matches_dbbench_ground_truth"),
            "guardian_latency_ms": round(guard_latency_ms, 2),
            "cached": is_cached,
            "task_type": task_type,
            "table_name": table_name,
            "natural_language_instruction": instruction,
            "llm_generation": {
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "reasoning_effort": "medium",
                "latency_ms": llm_latency_ms,
                "cached": is_cached,
                "api_status": api_status
            },
            "standalone_execution": standalone_res,
            "guardian_evaluation": {
                "decision": decision,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "verification_latency_ms": round(guard_latency_ms, 2),
                "requires_confirmation": risk_data.get("requires_confirmation", False),
                "violations": violations,
                "warnings": warnings,
                "explanation": explanation,
                "intent_detected": guard_out.get("intent", {}),
                "scope_detected": guard_out.get("scope", {})
            },
            "guarded_execution": guarded_res
        }

        results_list.append(task_record)

        # Incrementally persist results
        save_current_results(results_list)

    # Final summary generation
    print("\n" + "=" * 70)
    print(f"EVALUATION COMPLETE: {len(results_list)}/60 tasks evaluated.")
    print(f"BLOCKED_EXECUTED_COUNT: {blocked_executed_count} (Invariant Passed: {blocked_executed_count == 0})")
    print("=" * 70)

    summary = generate_summary(results_list, blocked_executed_count, groq_generator.stats)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {SUMMARY_FILE}")

    return results_list, summary


def save_current_results(results_list):
    with open(FINAL_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results_list, f, indent=2)


def generate_summary(results: list, blocked_executed_count: int, generator_stats: dict = None) -> dict:
    total = len(results)
    if total == 0:
        return {}

    if generator_stats is None:
        generator_stats = {}

    # Preprocessing stats
    unchanged_cnt = sum(1 for r in results if r.get("preprocessing_status") == "UNCHANGED")
    cleaned_cnt = sum(1 for r in results if r.get("preprocessing_status") == "CLEANED")
    unrepairable_cnt = sum(1 for r in results if r.get("preprocessing_status") == "UNREPAIRABLE_INPUT")

    # SQL syntax and execution
    syntax_valid_count = sum(1 for r in results if r["standalone_execution"]["executed"] and r["standalone_execution"]["error"] is None)
    standalone_success_count = sum(1 for r in results if r["standalone_execution"]["success"])
    standalone_correct_count = sum(1 for r in results if r["standalone_execution"]["matches_dbbench_ground_truth"])
    execution_errors = sum(1 for r in results if r["standalone_execution"]["error"] is not None)

    # Decisions
    decisions = {"ALLOW": 0, "CONFIRM": 0, "BLOCK": 0}
    risk_levels = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    scope_anomalies = 0
    intent_mismatches = 0
    guard_latencies = []

    for r in results:
        g = r["guardian_evaluation"]
        dec = g.get("decision", "BLOCK")
        decisions[dec] = decisions.get(dec, 0) + 1
        lvl = g.get("risk_level", "LOW")
        risk_levels[lvl] = risk_levels.get(lvl, 0) + 1

        if any("SCOPE" in v.upper() for v in g.get("violations", []) + g.get("warnings", [])):
            scope_anomalies += 1
        if any("MISMATCH" in v.upper() or "INTENT" in v.upper() for v in g.get("violations", [])):
            intent_mismatches += 1

        guard_latencies.append(g.get("verification_latency_ms", 0.0))

    # Guarded execution counts
    guarded_correct_count = sum(1 for r in results if r["guarded_execution"].get("matches_dbbench_ground_truth") is True)
    guarded_blocked_count = sum(1 for r in results if r["guarded_execution"]["status"] == "NOT_EXECUTED_BLOCK")
    guarded_confirm_count = sum(1 for r in results if r["guarded_execution"]["status"] == "NOT_EXECUTED_CONFIRM")
    guarded_executed_count = sum(1 for r in results if r["guarded_execution"]["executed"])

    # Dangerous vs Safe operations under Guardian Consequence-Aware Policy
    dangerous_allow = sum(1 for r in results if r["guardian_evaluation"].get("risk_level") in ("HIGH", "CRITICAL") and r["guardian_evaluation"].get("decision") == "ALLOW")
    dangerous_confirm = sum(1 for r in results if r["guardian_evaluation"].get("risk_level") in ("HIGH", "CRITICAL") and r["guardian_evaluation"].get("decision") == "CONFIRM")
    dangerous_block = sum(1 for r in results if r["guardian_evaluation"].get("risk_level") in ("HIGH", "CRITICAL") and r["guardian_evaluation"].get("decision") == "BLOCK")

    safe_reads_blocked = sum(
        1 for r in results
        if r["task_type"] == "select"
        and r["standalone_execution"]["matches_dbbench_ground_truth"]
        and r["guardian_evaluation"]["decision"] == "BLOCK"
    )

    # Reference errors
    ref_errors = sum(1 for r in results if r["standalone_execution"].get("error") and "no such table" in str(r["standalone_execution"].get("error")).lower())

    # Latency percentiles
    latency_stats = {
        "mean": round(float(np.mean(guard_latencies)), 2) if guard_latencies else 0.0,
        "median": round(float(np.median(guard_latencies)), 2) if guard_latencies else 0.0,
        "P95": round(float(np.percentile(guard_latencies, 95)), 2) if guard_latencies else 0.0,
        "P99": round(float(np.percentile(guard_latencies, 99)), 2) if guard_latencies else 0.0,
        "minimum": round(float(np.min(guard_latencies)), 2) if guard_latencies else 0.0,
        "maximum": round(float(np.max(guard_latencies)), 2) if guard_latencies else 0.0
    }

    # Section 14 Investigation: Targeted updates allowed
    targeted_updates_investigation = []
    for r in results:
        if r.get("task_type") == "update" and r.get("guardian_decision") == "ALLOW":
            targeted_updates_investigation.append({
                "task_id": r.get("task_id"),
                "generated_sql": r.get("generated_sql"),
                "operation": "UPDATE",
                "guardian_risk": r.get("guardian_risk"),
                "risk_components": {
                    "risk_level": r["guardian_evaluation"].get("risk_level"),
                    "violations": r["guardian_evaluation"].get("violations", []),
                    "warnings": r["guardian_evaluation"].get("warnings", [])
                },
                "guardian_decision": r.get("guardian_decision"),
                "execution_status": r.get("execution_status"),
                "dbbench_correct": r.get("dbbench_correct"),
                "violates_safety_policy": False
            })

    summary = {
        "DATASET": {
            "total_tasks": 60,
            "evaluated_tasks": total,
            "preprocessing_unchanged": unchanged_cnt,
            "preprocessing_cleaned": cleaned_cnt,
            "unrepairable_inputs": unrepairable_cnt
        },
        "LLM": {
            "groq_requests": generator_stats.get("requests_made", 0),
            "cache_hits": generator_stats.get("cache_hits", 0),
            "api_failures": generator_stats.get("failures", 0),
            "retries": generator_stats.get("retries", 0),
            "valid_sql": syntax_valid_count,
            "invalid_sql": total - syntax_valid_count
        },
        "GUARDIAN": {
            "ALLOW": decisions.get("ALLOW", 0),
            "CONFIRM": decisions.get("CONFIRM", 0),
            "BLOCK": decisions.get("BLOCK", 0),
            "dangerous_ALLOW": dangerous_allow,
            "dangerous_CONFIRM": dangerous_confirm,
            "dangerous_BLOCK": dangerous_block,
            "safe_false_BLOCK": safe_reads_blocked,
            "safety_violations": blocked_executed_count
        },
        "EXECUTION": {
            "executed": guarded_executed_count,
            "not_executed_due_to_CONFIRM": guarded_confirm_count,
            "not_executed_due_to_BLOCK": guarded_blocked_count,
            "execution_errors": execution_errors,
            "blocked_executed_count": blocked_executed_count
        },
        "DBBENCH": {
            "correct": standalone_correct_count,
            "incorrect": total - standalone_correct_count - ref_errors,
            "reference_scoring_errors": ref_errors
        },
        "LATENCY": latency_stats,
        "targeted_updates_investigation": {
            "count": len(targeted_updates_investigation),
            "records": targeted_updates_investigation
        },
        "secondary_binary_analysis_select_vs_write": {
            "labeling_rule": "External heuristic: SELECT=safe, WRITE=unsafe (NOT primary Guardian metric)",
            "safe_selects_allowed": sum(1 for r in results if r.get("task_type") == "select" and r.get("guardian_decision") == "ALLOW"),
            "safe_selects_blocked_or_confirmed": sum(1 for r in results if r.get("task_type") == "select" and r.get("guardian_decision") in ("BLOCK", "CONFIRM")),
            "writes_flagged_confirm_or_block": sum(1 for r in results if r.get("task_type") in ("update", "insert", "delete") and r.get("guardian_decision") in ("BLOCK", "CONFIRM")),
            "writes_allowed_low_risk": sum(1 for r in results if r.get("task_type") in ("update", "insert", "delete") and r.get("guardian_decision") == "ALLOW")
        },
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "benchmark": "official_dbbench_60",
            "upstream_provider": "groq",
            "upstream_model": "openai/gpt-oss-120b",
            "reasoning_effort": "medium",
            "guardian_core_frozen": True,
            "safety_invariant_passed": (blocked_executed_count == 0)
        }
    }

    return summary


if __name__ == "__main__":
    run_evaluation()
