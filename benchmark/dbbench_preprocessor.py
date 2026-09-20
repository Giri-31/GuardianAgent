"""
dbbench_preprocessor.py

Deterministic Preprocessing & Audit Trail for DBBench Tasks
============================================================

Performs semantics-preserving formatting and serialization cleanup
on official DBBench tasks without altering task semantics, operations,
table names, column names, or values.

Outputs:
  benchmark/dbbench_original/tasks_original.json
  benchmark/dbbench_cleaned/tasks_cleaned.json
  benchmark/dbbench_60_preprocessing_report.json
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dbbench_loader import load_dbbench

ORIGINAL_DIR = ROOT / "benchmark" / "dbbench_original"
CLEANED_DIR = ROOT / "benchmark" / "dbbench_cleaned"
REPORT_PATH = ROOT / "benchmark" / "dbbench_60_preprocessing_report.json"


def clean_description(text: str):
    """
    Deterministic cleanup of formatting/serialization corruption only.
    Returns: (cleaned_text, was_modified, modifications_list, status)
    """
    if not text or not isinstance(text, str):
        return "", True, ["empty_or_non_string_input"], "UNREPAIRABLE_INPUT"

    original = text
    cleaned = text
    modifications = []

    # 1. Strip accidental markdown code blocks
    if "```" in cleaned:
        cleaned_no_fences = re.sub(r"```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned_no_fences = re.sub(r"\s*```", "", cleaned_no_fences)
        if cleaned_no_fences != cleaned:
            cleaned = cleaned_no_fences
            modifications.append("removed_markdown_code_fences")

    # 2. Normalize smart unicode quotes to standard ascii quotes
    unicode_replacements = [
        ("\u201c", '"'),  # left double quotation mark
        ("\u201d", '"'),  # right double quotation mark
        ("\u2018", "'"),  # left single quotation mark
        ("\u2019", "'"),  # right single quotation mark / apostrophe
        ("\u2014", "--"), # em-dash
        ("\u2013", "-"),  # en-dash
        ("\u00a0", " "),  # non-breaking space
    ]
    for orig_char, repl_char in unicode_replacements:
        if orig_char in cleaned:
            cleaned = cleaned.replace(orig_char, repl_char)
            modifications.append(f"normalized_unicode_{repr(orig_char)}_to_{repr(repl_char)}")

    # 3. Fix unescaped/corrupted serialization escape sequences (e.g. \\" inside plain text)
    if r'\"' in cleaned:
        cleaned = cleaned.replace(r'\"', '"')
        modifications.append("unescaped_escaped_double_quotes")
    if r"\'" in cleaned:
        cleaned = cleaned.replace(r"\'", "'")
        modifications.append("unescaped_escaped_single_quotes")

    # 4. Collapse duplicated whitespace / carriage returns
    if "\r\n" in cleaned:
        cleaned = cleaned.replace("\r\n", "\n")
        modifications.append("normalized_crlf_to_lf")

    cleaned_ws = re.sub(r"[ \t]+", " ", cleaned)
    if cleaned_ws != cleaned:
        cleaned = cleaned_ws
        modifications.append("collapsed_consecutive_spaces")

    # 5. Trim leading/trailing whitespace
    stripped = cleaned.strip()
    if stripped != cleaned:
        cleaned = stripped
        modifications.append("trimmed_surrounding_whitespace")

    # Verify semantic integrity
    if not cleaned:
        return original, True, ["input_reduced_to_empty"], "UNREPAIRABLE_INPUT"

    was_modified = (cleaned != original)
    status = "CLEANED" if was_modified else "UNCHANGED"

    return cleaned, was_modified, modifications, status


def run_preprocessing():
    ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)

    raw_tasks = load_dbbench()
    assert len(raw_tasks) == 60, f"Expected 60 DBBench tasks, found {len(raw_tasks)}"

    reports = []
    cleaned_tasks = []

    for task in raw_tasks:
        case_id = task["case_id"]
        orig_desc = task.get("description", "")
        cleaned_desc, was_mod, mods, status = clean_description(orig_desc)

        report = {
            "task_id": case_id,
            "original_input": orig_desc,
            "cleaned_input": cleaned_desc,
            "was_modified": was_mod,
            "modifications": mods,
            "preprocessing_status": status,
        }
        reports.append(report)

        # Create cleaned task representation preserving immutable original fields
        cleaned_task = dict(task)
        cleaned_task["description"] = cleaned_desc
        cleaned_task["original_description"] = orig_desc
        cleaned_task["preprocessing_status"] = status
        cleaned_tasks.append(cleaned_task)

    # Save immutable original copy
    with open(ORIGINAL_DIR / "tasks_original.json", "w", encoding="utf-8") as f:
        json.dump(raw_tasks, f, indent=2)

    # Save cleaned tasks
    with open(CLEANED_DIR / "tasks_cleaned.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_tasks, f, indent=2)

    # Save preprocessing report
    GROQ_REPORT_PATH = ROOT / "benchmark" / "dbbench_60_groq_preprocessing_report.json"
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)
    with open(GROQ_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2)

    unchanged = sum(1 for r in reports if r["preprocessing_status"] == "UNCHANGED")
    cleaned_cnt = sum(1 for r in reports if r["preprocessing_status"] == "CLEANED")
    unrepairable = sum(1 for r in reports if r["preprocessing_status"] == "UNREPAIRABLE_INPUT")

    print("=" * 60)
    print("DBBENCH PREPROCESSING REPORT")
    print("=" * 60)
    print(f"Total tasks processed: {len(reports)}")
    print(f"  UNCHANGED          : {unchanged}")
    print(f"  CLEANED            : {cleaned_cnt}")
    print(f"  UNREPAIRABLE_INPUT : {unrepairable}")
    print(f"Report written to    : {REPORT_PATH}")
    print(f"Original tasks saved : {ORIGINAL_DIR / 'tasks_original.json'}")
    print(f"Cleaned tasks saved  : {CLEANED_DIR / 'tasks_cleaned.json'}")
    print("=" * 60)

    return reports, cleaned_tasks


if __name__ == "__main__":
    run_preprocessing()
