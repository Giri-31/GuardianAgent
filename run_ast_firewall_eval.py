#!/usr/bin/env python3
"""
Standalone CLI Runner for the AST SQL Policy Firewall Evaluation.
Usage:
    python run_ast_firewall_eval.py --dataset bird_eval/results/bird_fresh_mutations_dataset.json --output bird_eval/ast_firewall/results/heldout_342_results.json
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bird_eval.ast_firewall.evaluator import ASTFirewallEvaluator
from bird_eval.ast_firewall.firewall import ASTSQLPolicyFirewall
from bird_eval.ast_firewall.schema_analyzer import SchemaAnalyzer
from bird_eval.ast_firewall.config import DEFAULT_DEV_DATABASES_DIR


def main():
    parser = argparse.ArgumentParser(description="Run AST SQL Policy Firewall Evaluation")
    parser.add_argument("--dataset", required=True, help="Path to evaluation dataset JSON")
    parser.add_argument("--output", required=True, help="Path to write evaluation results JSON")
    parser.add_argument("--schema-dir", default=DEFAULT_DEV_DATABASES_DIR, help="Path to SQLite databases dir")
    parser.add_argument("--type", choices=["mutation", "benign", "auto"], default="auto", help="Dataset type")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Error: Dataset file not found: {dataset_path}")
        sys.exit(1)

    ds_type = args.type
    if ds_type == "auto":
        ds_type = "benign" if ("benign" in str(dataset_path).lower() or "clean" in str(dataset_path).lower()) else "mutation"

    print(f"==================================================")
    print(f"Running AST SQL Policy Firewall Evaluation")
    print(f"Dataset: {dataset_path} (Type: {ds_type})")
    print(f"Schema Directory: {args.schema_dir}")
    print(f"Output: {args.output}")
    print(f"==================================================")

    schema_analyzer = SchemaAnalyzer(databases_dir=args.schema_dir)
    firewall = ASTSQLPolicyFirewall(schema_analyzer=schema_analyzer)
    evaluator = ASTFirewallEvaluator(firewall=firewall)

    eval_result = evaluator.evaluate_dataset(str(dataset_path), dataset_type=ds_type)

    out_p = Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(eval_result, f, indent=2)

    metrics = eval_result["overall_metrics"]
    lat = eval_result["latency_ms"]
    cm = eval_result["confusion_matrix"]

    print("\n--- RESULTS SUMMARY ---")
    print(f"Total Cases:            {metrics['total']}")
    print(f"Correct Decisions:      {metrics['correct']} / {metrics['total']} ({metrics['accuracy_pct']}%)")
    print(f"Safety Interception:    {metrics['safety_interception_pct']}%")
    print(f"Dangerous Miss Rate:    {metrics['dangerous_miss_rate_pct']}%")
    print(f"Benign False-Block Rate:{metrics['benign_false_block_pct']}%")
    print(f"Parser Failures:        {metrics['parser_failures']} ({metrics['parser_failure_rate_pct']}%)")
    print(f"Latency (mean / med):   {lat['mean_ms']} ms / {lat['median_ms']} ms")
    print(f"Confusion Matrix:       True Safe={cm['true_safe']}, False Unsafe={cm['false_unsafe']}, False Safe={cm['false_safe']}, True Unsafe={cm['true_unsafe']}")
    print(f"Saved full results to:  {out_p}")


if __name__ == "__main__":
    main()
