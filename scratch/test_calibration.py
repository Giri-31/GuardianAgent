import json
import os
import sys
from pathlib import Path

os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STRICT"
os.environ["GUARDIAN_DISABLE_LLM"] = "1"
sys.path.insert(0, ".")

import intent_analyzer
import risk_engine
from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DEV_DATABASES_DIR = Path("bird_eval/databases/data_minidev/MINIDEV/dev_databases")

ENGLISH_STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
    "from", "by", "of", "about", "as", "into", "like", "through", "after",
    "over", "between", "out", "against", "during", "without", "before",
    "under", "around", "among", "this", "that", "these", "those", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "more", "most", "less", "least", "all", "any",
    "some", "no", "not", "where", "order", "which", "what", "who", "whom"
}

# 1. Patch clean in intent_analyzer to treat English stopwords as unknown
orig_clean = intent_analyzer._clean
def clean_with_stopwords(val):
    res = orig_clean(val)
    if res.lower() in ENGLISH_STOPWORDS:
        return "unknown"
    return res

intent_analyzer._clean = clean_with_stopwords

# 2. Patch risk_engine overrides for FIELD_MISMATCH on SELECT
orig_overrides = risk_engine._apply_safety_overrides
def calibrated_overrides(operation, mismatches, scope, impact_level, risk_score):
    is_select = (operation == "SELECT")
    has_field_mm = ("FIELD_MISMATCH" in mismatches)
    
    # We run orig_overrides without FIELD_MISMATCH if SELECT
    mms_to_pass = [m for m in mismatches if not (is_select and m == "FIELD_MISMATCH")]
    score = orig_overrides(operation, mms_to_pass, scope, impact_level, risk_score)
    
    if is_select and has_field_mm:
        # If it's a SELECT with FIELD_MISMATCH, demote to CONFIRM (4.0)
        # But if TARGET_MISMATCH is present in STRICT mode, it stays 7.0 (BLOCK)
        if "TARGET_MISMATCH" in mismatches and os.environ.get("GUARDIAN_READ_SAFETY_LEVEL", "STANDARD").upper() == "STRICT":
            score = max(score, 7.0)
        elif "OPERATION_MISMATCH" in mismatches:
            score = max(score, 10.0)
        else:
            score = max(score, 4.0)
    elif not is_select and has_field_mm:
        score = max(score, 7.0)
        
    return score

risk_engine._apply_safety_overrides = calibrated_overrides

# Load test data
with open("bird_eval/results/bird_fresh_mutations_dataset.json", encoding="utf-8") as f:
    data = json.load(f)

seen = set()
clean_cases = []
for m in data["mutations"]:
    qid = m["source_question_id"]
    if qid not in seen:
        seen.add(qid)
        clean_cases.append({
            "qid": qid,
            "db_id": m["db_id"],
            "q": m["original_question"],
            "sql": m["gold_sql"]
        })

adapter = GuardianBIRDAdapter(disable_llm_intent=True)

# Test Benign queries
benign_decisions = {}
for item in clean_cases:
    db_id = item["db_id"]
    db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
    if not db_path.exists():
        matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
        if matches: db_path = matches[0]
    conn = adapter.open_database_connection(db_path, read_only=True)
    res = adapter.evaluate_query(item["q"], item["sql"], connection=conn)
    conn.close()
    d = res["decision"]
    benign_decisions[d] = benign_decisions.get(d, 0) + 1

print("=" * 60)
print("CALIBRATED BENIGN QUERY RESULTS (50 Clean Queries):")
print(benign_decisions)
print("=" * 60)

# Test Fresh Mutations (342 mutations)
mutations = data["mutations"]
mut_correct = 0
mut_cats = {}
for m in mutations:
    cat = m["mutation_category"]
    exp = m["expected_decision"]
    db_id = m["db_id"]
    db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
    if not db_path.exists():
        matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
        if matches: db_path = matches[0]
    conn = adapter.open_database_connection(db_path, read_only=True)
    res = adapter.evaluate_query(m["original_question"], m["mutated_sql"], connection=conn)
    conn.close()
    act = res["decision"]
    corr = (act == exp) or (exp == "CONFIRM" and act in ("CONFIRM", "BLOCK"))
    if cat not in mut_cats: mut_cats[cat] = {"total": 0, "correct": 0}
    mut_cats[cat]["total"] += 1
    if corr:
        mut_correct += 1
        mut_cats[cat]["correct"] += 1

print("\nCALIBRATED FRESH MUTATIONS RESULTS (342 Mutations):")
print(f"Total Correct: {mut_correct} / {len(mutations)} ({mut_correct/len(mutations)*100:.2f}%)")
for c, st in sorted(mut_cats.items()):
    print(f"  {c:<25}: {st['correct']}/{st['total']} ({st['correct']/st['total']*100:.1f}%)")

