"""
Evaluator module for the AST SQL Policy Firewall.
Runs batch evaluation across development, held-out, and benign benchmark datasets.
Computes metrics, confusion matrices, latency statistics, category breakdowns, and root-cause error analysis.
"""

import json
import statistics
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from .firewall import ASTSQLPolicyFirewall, FirewallResult
from .config import AST_FIREWALL_VERSION


class ASTFirewallEvaluator:
    """
    Independent evaluation harness for AST SQL Policy Firewall.
    Strictly uses ONLY SQL + database schema during prediction.
    Metadata and expected labels are used ONLY post-prediction for scoring.
    """

    def __init__(self, firewall: Optional[ASTSQLPolicyFirewall] = None, databases_dir: Optional[str] = None):
        self.firewall = firewall or ASTSQLPolicyFirewall(databases_dir=databases_dir)

    def _normalize_expected(self, raw_expected: Optional[str]) -> str:
        """
        Maps GuardianAgent/BIRD expected decisions to binary SAFE / UNSAFE:
        - ALLOW -> SAFE
        - BLOCK, CONFIRM -> UNSAFE
        """
        if not raw_expected:
            return "UNKNOWN"
        raw_upper = str(raw_expected).strip().upper()
        if raw_upper == "ALLOW":
            return "SAFE"
        if raw_upper in ("BLOCK", "CONFIRM", "UNSAFE"):
            return "UNSAFE"
        return "UNKNOWN"

    def _classify_error_root_cause(self, case: Dict[str, Any], result: FirewallResult, expected_binary: str) -> str:
        """
        Categorizes root cause of prediction error.
        """
        category = case.get("mutation_category", "UNKNOWN")

        if result.is_parser_failure:
            return "Parser limitation (syntax error or unsupported dialect construct)"

        if expected_binary == "UNSAFE" and result.decision == "SAFE":
            if category in ("TARGET_MISMATCH", "FIELD_INJECT"):
                return "Semantic mismatch not visible in AST (pure SQL is structurally valid)"
            elif category == "SCOPE_ESCALATION":
                return "Natural-language scope not available (WHERE predicate structurally valid but violates intent)"
            elif category == "DANGEROUS_DELETE_WHERE":
                return "Natural-language scope not available (DELETE has WHERE clause, but action violates user intent)"
            elif result.operation in ("SELECT", "UPDATE", "DELETE"):
                return "Intent-conditioned safety requirement not detectable from structural AST"
            else:
                return "Policy limitation (destructive write not matched by rule)"

        if expected_binary == "SAFE" and result.decision == "UNSAFE":
            if any("UNKNOWN_TABLE" in v for v in result.violations):
                return "Schema-resolution limitation (valid table/alias unresolved in schema)"
            return "Valid complex SQL incorrectly rejected by structural policy"

        return "Other"

    def evaluate_dataset(
        self,
        dataset_path: str,
        dataset_type: str = "mutation",  # "mutation" or "benign"
    ) -> Dict[str, Any]:
        """
        Evaluates the firewall on a JSON dataset.
        """
        p = Path(dataset_path)
        with open(p, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        if isinstance(raw_data, dict) and "mutations" in raw_data:
            cases = raw_data["mutations"]
        elif isinstance(raw_data, list):
            cases = raw_data
        else:
            raise ValueError(f"Unsupported dataset format in {dataset_path}")

        records: List[Dict[str, Any]] = []
        latencies: List[float] = []

        total_cases = len(cases)
        correct_count = 0
        parser_failures = 0

        # Confusion matrix counters: Expected vs Predicted
        # SAFE vs UNSAFE
        cm = {
            "true_safe": 0,       # Expected SAFE, Predicted SAFE
            "false_unsafe": 0,    # Expected SAFE, Predicted UNSAFE (False-Block)
            "false_safe": 0,      # Expected UNSAFE, Predicted SAFE (Dangerous Miss)
            "true_unsafe": 0,     # Expected UNSAFE, Predicted UNSAFE (Interception)
        }

        category_stats: Dict[str, Dict[str, int]] = {}
        error_records: List[Dict[str, Any]] = []

        for idx, case in enumerate(cases):
            # Extract SQL query
            sql = case.get("mutated_sql") or case.get("generated_or_mutated_sql") or case.get("gold_sql") or ""
            db_id = case.get("db_id") or ""
            raw_expected = case.get("expected_decision") or "ALLOW" if dataset_type == "benign" else "BLOCK"
            expected_binary = self._normalize_expected(raw_expected)
            cat = case.get("mutation_category") or ("BENIGN_QUERY" if dataset_type == "benign" else "UNKNOWN")

            if cat not in category_stats:
                category_stats[cat] = {"total": 0, "predicted_safe": 0, "predicted_unsafe": 0, "correct": 0}

            # RUN FIREWALL (STRICTLY SQL + DB_ID ONLY)
            res: FirewallResult = self.firewall.check_query(sql=sql, db_id=db_id)
            latencies.append(res.latency_ms)

            if res.is_parser_failure:
                parser_failures += 1

            category_stats[cat]["total"] += 1
            if res.decision == "SAFE":
                category_stats[cat]["predicted_safe"] += 1
            else:
                category_stats[cat]["predicted_unsafe"] += 1

            is_correct = (res.decision == expected_binary)
            if is_correct:
                correct_count += 1
                category_stats[cat]["correct"] += 1

            # Update confusion matrix
            if expected_binary == "SAFE":
                if res.decision == "SAFE":
                    cm["true_safe"] += 1
                else:
                    cm["false_unsafe"] += 1
            elif expected_binary == "UNSAFE":
                if res.decision == "UNSAFE":
                    cm["true_unsafe"] += 1
                else:
                    cm["false_safe"] += 1

            # Error recording
            if not is_correct:
                root_cause = self._classify_error_root_cause(case, res, expected_binary)
                error_records.append({
                    "case_index": idx,
                    "db_id": db_id,
                    "question": case.get("original_question", ""),
                    "sql": sql,
                    "expected_raw": raw_expected,
                    "expected_binary": expected_binary,
                    "predicted_binary": res.decision,
                    "mutation_category": cat,
                    "operation": res.operation,
                    "tables": res.tables,
                    "violations": res.violations,
                    "root_cause": root_cause,
                })

            records.append({
                "case_index": idx,
                "db_id": db_id,
                "question": case.get("original_question", ""),
                "sql": sql,
                "expected_raw": raw_expected,
                "expected_binary": expected_binary,
                "predicted_decision": res.decision,
                "decision_correct": is_correct,
                "mutation_category": cat,
                "violations": res.violations,
                "operation": res.operation,
                "tables": res.tables,
                "where_present": res.where_present,
                "is_parser_failure": res.is_parser_failure,
                "latency_ms": res.latency_ms,
            })

        # Calculate summary metrics
        accuracy_pct = round((correct_count / total_cases * 100.0), 2) if total_cases > 0 else 0.0
        total_unsafe_expected = cm["true_unsafe"] + cm["false_safe"]
        total_safe_expected = cm["true_safe"] + cm["false_unsafe"]

        safety_interception_pct = (
            round((cm["true_unsafe"] / total_unsafe_expected * 100.0), 2)
            if total_unsafe_expected > 0
            else 0.0
        )
        dangerous_miss_rate_pct = (
            round((cm["false_safe"] / total_unsafe_expected * 100.0), 2)
            if total_unsafe_expected > 0
            else 0.0
        )
        benign_false_block_pct = (
            round((cm["false_unsafe"] / total_safe_expected * 100.0), 2)
            if total_safe_expected > 0
            else 0.0
        )
        parser_failure_rate_pct = (
            round((parser_failures / total_cases * 100.0), 2)
            if total_cases > 0
            else 0.0
        )

        latency_summary = {
            "mean_ms": round(statistics.mean(latencies), 4) if latencies else 0.0,
            "median_ms": round(statistics.median(latencies), 4) if latencies else 0.0,
            "min_ms": round(min(latencies), 4) if latencies else 0.0,
            "max_ms": round(max(latencies), 4) if latencies else 0.0,
        }

        # Category breakdown percentages
        category_breakdown = {}
        for c_name, stats in category_stats.items():
            tot = stats["total"]
            category_breakdown[c_name] = {
                "total": tot,
                "predicted_safe": stats["predicted_safe"],
                "predicted_unsafe": stats["predicted_unsafe"],
                "correct": stats["correct"],
                "interception_rate_pct": round(stats["predicted_unsafe"] / tot * 100.0, 2) if tot > 0 else 0.0,
                "accuracy_pct": round(stats["correct"] / tot * 100.0, 2) if tot > 0 else 0.0,
            }

        return {
            "metadata": {
                "version": AST_FIREWALL_VERSION,
                "dataset_path": str(p),
                "dataset_type": dataset_type,
                "total_cases": total_cases,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "overall_metrics": {
                "total": total_cases,
                "correct": correct_count,
                "accuracy_pct": accuracy_pct,
                "dangerous_miss_rate_pct": dangerous_miss_rate_pct,
                "safety_interception_pct": safety_interception_pct,
                "benign_false_block_pct": benign_false_block_pct,
                "parser_failures": parser_failures,
                "parser_failure_rate_pct": parser_failure_rate_pct,
            },
            "confusion_matrix": cm,
            "latency_ms": latency_summary,
            "category_breakdown": category_breakdown,
            "error_analysis": {
                "total_errors": len(error_records),
                "errors": error_records,
            },
            "records": records,
        }
