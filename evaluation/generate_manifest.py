"""
Generate final_experiment_manifest.json.
"""

import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

def file_sha256(path):
    p = Path(path)
    if not p.exists():
        return "file_not_found"
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def get_git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"

manifest = {
    "experiment_title": "GuardianAgent Final IEEE Conference Experimental Freeze",
    "version": "2.0-calibrated-frozen",
    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "git_commit": get_git_commit(),
    "environment": {
        "os": platform.platform(),
        "python_version": sys.version,
        "sqlite_version": "3.50.4",
        "sqlglot_version": "30.19.0",
        "env_vars": {
            "GUARDIAN_DISABLE_LLM": "1",
            "GUARDIAN_READ_SAFETY_LEVEL": "STRICT"
        }
    },
    "guardian_configuration": {
        "risk_formula": "R = 0.20 * S_operation + 0.40 * S_mismatch + 0.25 * S_scope + 0.15 * S_impact",
        "weights": {
            "w_operation": 0.20,
            "w_mismatch": 0.40,
            "w_scope": 0.25,
            "w_impact": 0.15
        },
        "thresholds": {
            "low_allow_max": 2.99,
            "medium_confirm_min": 3.00,
            "medium_confirm_max": 6.99,
            "high_block_min": 7.00
        },
        "overrides": {
            "DROP": "BLOCK (10.0)",
            "TRUNCATE": "BLOCK (10.0)",
            "ALTER": "BLOCK (10.0)",
            "DELETE_NO_WHERE": "BLOCK (10.0)",
            "UPDATE_NO_WHERE": "BLOCK (9.0)",
            "DANGEROUS_DELETE_WHERE": "BLOCK (10.0)",
            "SELECT_FIELD_MISMATCH": "CONFIRM (4.0)",
            "SELECT_TARGET_MISMATCH_STRICT": "BLOCK (7.0)"
        }
    },
    "datasets": {
        "heldout_bird_mutations_342": {
            "path": "bird_eval/results/bird_fresh_mutations_dataset.json",
            "sha256": file_sha256("bird_eval/results/bird_fresh_mutations_dataset.json"),
            "total_cases": 342,
            "databases_count": 10,
            "purpose": "Primary Generalization Safety Benchmark"
        },
        "benign_bird_queries_50": {
            "path": "bird_eval/results/bird_mini_dev_50_eval.json",
            "sha256": file_sha256("bird_eval/results/bird_mini_dev_50_eval.json"),
            "total_cases": 50,
            "databases_count": 10,
            "purpose": "Usability & False-Block Evaluation"
        },
        "development_bird_mutations_336": {
            "path": "bird_eval/results/bird_mutations_dataset.json",
            "sha256": file_sha256("bird_eval/results/bird_mutations_dataset.json"),
            "total_cases": 336,
            "databases_count": 2,
            "purpose": "Development, Calibration & Debugging"
        },
        "dbbench_agent_tasks_60": {
            "path": "benchmark/dbbench_cleaned/tasks_cleaned.json",
            "sha256": file_sha256("benchmark/dbbench_cleaned/tasks_cleaned.json"),
            "total_tasks": 60,
            "purpose": "End-to-End Multi-Turn Agent Evaluation"
        }
    },
    "key_results_summary": {
        "heldout_342": {
            "strict_block_accuracy_pct": 91.81,
            "safety_interception_rate_pct": 97.37,
            "autonomous_escape_rate_pct": 2.63,
            "catastrophic_write_escape_count": 0,
            "catastrophic_write_total": 200,
            "catastrophic_write_escape_rate_pct": 0.0
        },
        "benign_50": {
            "allow_count": 31,
            "confirm_count": 19,
            "block_count": 0,
            "false_block_rate_pct": 0.0,
            "interruption_rate_pct": 38.0
        },
        "dbbench_60": {
            "task_success_rate_pct": 76.67,
            "safety_violations": 0,
            "dangerous_sql_escapes": 0,
            "human_intervention_pct": 13.33
        }
    }
}

out_p = Path("evaluation/final_experiment_manifest.json")
out_p.parent.mkdir(parents=True, exist_ok=True)
with open(out_p, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)

print(f"Generated {out_p} successfully.")
