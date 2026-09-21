"""
run_phase4_llm_reeval.py

Phase 4: LLM Intent Mode Re-Evaluation of Missed Mutations.

Reads the Phase 3 mutation eval results, extracts all cases where
GuardianAgent gave the WRONG decision (decision_correct=False),
and re-evaluates them with the Gemini LLM intent analyzer enabled.

This isolates the contribution of LLM-based intent analysis vs.
deterministic mode on the hardest cases (TARGET_MISMATCH, SCOPE_ESCALATION,
FIELD_INJECT).

Outputs:
  bird_eval/results/bird_phase4_llm_reeval_results.json
  bird_eval/results/bird_phase4_llm_reeval_summary.json

Usage:
  python bird_eval/scripts/run_phase4_llm_reeval.py
  python bird_eval/scripts/run_phase4_llm_reeval.py --categories TARGET_MISMATCH SCOPE_ESCALATION
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# LLM mode: ensure GUARDIAN_DISABLE_LLM is NOT set
os.environ.pop("GUARDIAN_DISABLE_LLM", None)

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter  # noqa: E402

PHASE3_RESULTS = ROOT / "bird_eval" / "results" / "bird_mutation_eval_results.json"
DEV_DATABASES_DIR = (
    ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
)
RESULTS_DIR = ROOT / "bird_eval" / "results"


def is_correct(expected: str, actual: str) -> bool:
    if expected == "BLOCK":
        return actual == "BLOCK"
    elif expected == "CONFIRM":
        return actual in ("BLOCK", "CONFIRM")
    elif expected == "ALLOW":
        return actual == "ALLOW"
    return False


def run_phase4_reeval(categories: list = None):
    print("=" * 80)
    print("BIRD PHASE 4 — LLM INTENT MODE RE-EVALUATION OF MISSED CASES")
    print("=" * 80)
    print("Intent Mode: Gemini LLM API (GUARDIAN_DISABLE_LLM unset)\n")

    if not PHASE3_RESULTS.exists():
        raise FileNotFoundError(
            f"Phase 3 results not found: {PHASE3_RESULTS}\n"
            "Run run_mutation_eval.py first."
        )

    with open(PHASE3_RESULTS, "r", encoding="utf-8") as f:
        all_results = json.load(f)

    # Filter to missed cases only
    missed = [r for r in all_results if not r.get("decision_correct", True)]

    if categories:
        missed = [r for r in missed if r["mutation_category"] in categories]

    print(f"Total missed cases in Phase 3 : {len([r for r in all_results if not r.get('decision_correct', True)])}")
    print(f"Cases selected for re-eval    : {len(missed)}")
    if categories:
        print(f"Category filter               : {categories}")
    print()

    adapter = GuardianBIRDAdapter(disable_llm_intent=False)  # LLM mode ON
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    improved_count = 0
    regressed_count = 0  # was correct in det mode → wrong in LLM mode (shouldn't happen here)
    category_stats = defaultdict(lambda: {"total": 0, "improved": 0, "still_wrong": 0})

    print(f"{'#':<5} {'MutID':<7} {'Category':<25} {'Exp':<8} {'Det':<8} {'LLM':<8} {'Change':<10}")
    print("-" * 75)

    for idx, miss in enumerate(missed, start=1):
        mut_id = miss.get("mutation_id", idx)
        db_id = miss["db_id"]
        question = miss["original_question"]
        mutated_sql = miss["mutated_sql"]
        expected = miss["expected_decision"]
        det_decision = miss["guardian_decision"]  # Phase 3 deterministic result
        category = miss["mutation_category"]

        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            if matches:
                db_path = matches[0]

        conn = None
        try:
            conn = adapter.open_database_connection(db_path, read_only=True)
            guardian_res = adapter.evaluate_query(
                user_request=question,
                sql=mutated_sql,
                connection=conn,
            )
        except Exception as e:
            guardian_res = {
                "decision": "BLOCK",
                "risk_score": 10.0,
                "risk_level": "CRITICAL",
                "mismatches": ["EVALUATION_EXCEPTION"],
                "latency_ms": 0.0,
                "error": str(e),
            }
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        llm_decision = guardian_res["decision"]
        llm_correct = is_correct(expected, llm_decision)
        det_correct = is_correct(expected, det_decision)

        improved = llm_correct and not det_correct
        regressed = not llm_correct and det_correct

        if improved:
            improved_count += 1
            change_str = "FIXED ✓"
        elif regressed:
            regressed_count += 1
            change_str = "REGRESSED"
        else:
            change_str = "still MISS"

        category_stats[category]["total"] += 1
        if improved:
            category_stats[category]["improved"] += 1
        else:
            category_stats[category]["still_wrong"] += 1

        print(
            f"[{idx:<4}] {mut_id:<7} {category:<25} {expected:<8} {det_decision:<8} {llm_decision:<8} {change_str}"
        )

        record = dict(miss)
        record.update({
            "phase3_det_decision": det_decision,
            "phase3_det_correct": det_correct,
            "phase4_llm_decision": llm_decision,
            "phase4_llm_correct": llm_correct,
            "phase4_risk_score": guardian_res.get("risk_score"),
            "phase4_risk_level": guardian_res.get("risk_level"),
            "phase4_mismatches": guardian_res.get("mismatches", []),
            "phase4_latency_ms": guardian_res.get("latency_ms"),
            "phase4_error": guardian_res.get("error"),
            "improved_by_llm": improved,
            "regressed_by_llm": regressed,
        })
        results.append(record)

    # -----------------------------------------------------------------------
    # Build summary
    # -----------------------------------------------------------------------
    total = len(results)

    # Per-category lift
    cat_breakdown = {}
    for cat, stats in sorted(category_stats.items()):
        t = stats["total"]
        imp = stats["improved"]
        cat_breakdown[cat] = {
            "total_retested": t,
            "improved": imp,
            "still_wrong": stats["still_wrong"],
            "lift_pct": round((imp / t) * 100, 2) if t else 0.0,
        }

    # Original Phase 3 overall metrics (over full 336 cases)
    phase3_total = len(all_results)
    phase3_correct = sum(1 for r in all_results if r.get("decision_correct", False))
    phase3_accuracy = round((phase3_correct / phase3_total) * 100, 2)

    # Compute hypothetical Phase 4 overall accuracy
    # (Phase 3 correct cases unchanged) + (Phase 3 missed cases re-evaluated)
    phase4_correct_total = phase3_correct + improved_count
    phase4_accuracy = round((phase4_correct_total / phase3_total) * 100, 2)

    summary = {
        "metadata": {
            "evaluation_phase": "Phase 4: LLM Intent Mode Re-Evaluation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intent_mode": "gemini_llm_api",
            "categories_filtered": categories,
            "cases_retested": total,
        },
        "phase3_baseline": {
            "total": phase3_total,
            "correct": phase3_correct,
            "missed": phase3_total - phase3_correct,
            "accuracy_pct": phase3_accuracy,
        },
        "phase4_reeval": {
            "cases_retested": total,
            "improved_by_llm": improved_count,
            "still_wrong_after_llm": total - improved_count,
            "regressed": regressed_count,
            "lift_pct": round((improved_count / total) * 100, 2) if total else 0.0,
        },
        "combined_hypothetical_accuracy": {
            "total": phase3_total,
            "correct_with_llm": phase4_correct_total,
            "accuracy_pct": phase4_accuracy,
            "improvement_over_deterministic_pct": round(phase4_accuracy - phase3_accuracy, 2),
        },
        "per_category_lift": cat_breakdown,
    }

    # Save
    results_path = RESULTS_DIR / "bird_phase4_llm_reeval_results.json"
    summary_path = RESULTS_DIR / "bird_phase4_llm_reeval_summary.json"

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("PHASE 4 LLM RE-EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Cases Retested              : {total}")
    print(f"Improved by LLM             : {improved_count}/{total} ({summary['phase4_reeval']['lift_pct']}%)")
    print(f"Still wrong after LLM       : {total - improved_count}")
    print(f"\nPhase 3 (Deterministic)     : {phase3_correct}/{phase3_total} ({phase3_accuracy}%)")
    print(f"Phase 4 (Combined w/ LLM)   : {phase4_correct_total}/{phase3_total} ({phase4_accuracy}%)")
    print(f"Improvement                 : +{summary['combined_hypothetical_accuracy']['improvement_over_deterministic_pct']}%")
    print(f"\nPer-Category Lift:")
    for cat, stats in cat_breakdown.items():
        print(f"  {cat:<30} {stats['improved']}/{stats['total_retested']} improved ({stats['lift_pct']}%)")
    print(f"\nResults : {results_path}")
    print(f"Summary : {summary_path}")
    print("=" * 80)

    return summary, results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Phase 4: Re-evaluate Phase 3 misses with Gemini LLM intent mode."
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=None,
        help="Limit re-eval to specific mutation categories (e.g. TARGET_MISMATCH SCOPE_ESCALATION).",
    )
    args = parser.parse_args()

    run_phase4_reeval(categories=args.categories)
