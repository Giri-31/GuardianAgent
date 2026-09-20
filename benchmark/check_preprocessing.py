import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbbench_loader import load_dbbench

tasks = load_dbbench()
print(f"Inspecting {len(tasks)} tasks for preprocessing...")

for t in tasks:
    desc = t["description"]
    # Check for formatting artifacts
    has_sql_wrapper = "```" in desc
    has_escaped_quotes = r"\"" in desc or r"\'" in desc
    has_trailing_ws = desc != desc.strip()
    if has_sql_wrapper or has_escaped_quotes or has_trailing_ws:
        print(f"Task {t['case_id']}: wrappers={has_sql_wrapper}, escaped_quotes={has_escaped_quotes}, ws={has_trailing_ws}")
        print(f"  Desc: {repr(desc)}")
