import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dbbench_loader import load_dbbench
from collections import Counter

tasks = load_dbbench()
print(f"Total tasks: {len(tasks)}")
types = Counter([str(t["type"]) for t in tasks])
print("Type breakdown:")
for t, c in types.items():
    print(f"  {t}: {c}")

has_label = sum(1 for t in tasks if t.get("label"))
has_md5 = sum(1 for t in tasks if t.get("answer_md5"))
has_sql = sum(1 for t in tasks if t.get("reference_sql"))
print(f"Tasks with label: {has_label}")
print(f"Tasks with answer_md5: {has_md5}")
print(f"Tasks with reference_sql: {has_sql}")
