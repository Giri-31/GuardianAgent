import os
import sys
import json
from pathlib import Path
os.environ["GUARDIAN_DISABLE_LLM"] = "1"
sys.path.insert(0, ".")
from intent_analyzer import analyze_intent

with open("bird_eval/results/bird_fresh_mutations_dataset.json", encoding="utf-8") as f:
    d = json.load(f)

seen = set()
for m in d["mutations"]:
    qid = m["source_question_id"]
    if qid not in seen:
        seen.add(qid)
        intent = analyze_intent(m["original_question"])
        fld = intent.get("field")
        tgt = intent.get("target")
        q = m["original_question"][:65]
        print(f"QID {qid:<4} field={str(fld):<15} target={str(tgt):<15} Q: {q}")
