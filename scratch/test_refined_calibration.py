import json
import os
import re
import sys
sys.path.insert(0, ".")
from pathlib import Path
from collections import Counter

os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STRICT"
os.environ["GUARDIAN_DISABLE_LLM"] = "1"

import intent_analyzer
import intent_sql_checker
import risk_engine
from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DEV_DATABASES_DIR = Path("bird_eval/databases/data_minidev/MINIDEV/dev_databases")

PREPOSITIONS_AND_DETERMINERS = {
    "than", "the", "a", "an", "after", "before", "over", "under", "above",
    "below", "between", "of", "to", "from", "in", "at", "by", "around",
    "since", "until", "or", "and", "is", "was", "were", "for", "with",
    "without", "no", "less", "more", "least", "most", "about", "into"
}

ENGLISH_STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
    "from", "by", "of", "about", "as", "into", "like", "through", "after",
    "over", "between", "out", "against", "during", "without", "before",
    "under", "around", "among", "this", "that", "these", "those", "is",
    "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "more", "most", "less", "least", "all", "any",
    "some", "no", "not", "where", "order", "which", "what", "who", "whom"
}

# 1. Stopwords in _clean
orig_clean = intent_analyzer._clean
def clean_with_stopwords(val):
    res = orig_clean(val)
    if res.lower() in ENGLISH_STOPWORDS:
        return "unknown"
    return res
intent_analyzer._clean = clean_with_stopwords

# 2. Refine _extract_descriptor_identifier to ignore prepositions
orig_extract_desc = intent_analyzer._extract_descriptor_identifier
def refined_extract_descriptor_identifier(text):
    pattern = re.compile(
        r"\b([A-Za-z][A-Za-z0-9_-]*)\s+(\d+)(?=\s|[.,!?;:]|$)",
        flags=re.IGNORECASE
    )
    for match in pattern.finditer(text):
        descriptor = match.group(1).lower()
        if descriptor in PREPOSITIONS_AND_DETERMINERS:
            continue
        prefix = text[:match.start()]
        if re.search(r"\b(?:to|as|set)\s*$", prefix, flags=re.IGNORECASE):
            continue
        return match.group(2)
    return "unknown"
intent_analyzer._extract_descriptor_identifier = refined_extract_descriptor_identifier

# 3. In intent_sql_checker, allow substring matching for target if len >= 3
orig_check_target = intent_sql_checker._check_filter_target
def refined_check_filter_target(operation, intent, sql, mismatches):
    # Call original first
    local_mm = []
    orig_check_target(operation, intent, sql, local_mm)
    if "TARGET_MISMATCH" not in local_mm:
        return
    # If original flagged TARGET_MISMATCH, check word match in predicates, table names, or raw SQL
    requested_target = intent.get("target")
    if requested_target and not intent_sql_checker._is_unknown(requested_target):
        norm_t = intent_sql_checker._normalize_sql_value(requested_target).lower()
        if len(norm_t) >= 3:
            # Check if target matches any table in FROM or JOIN
            raw_tables = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z0-9_`\"\[\]]+)", sql, re.IGNORECASE)
            clean_tables = [t.strip("`\"[]").lower() for t in raw_tables]
            if any(norm_t == t or norm_t in t.split("_") for t in clean_tables):
                return
            predicates = intent_sql_checker._extract_predicates(sql)
            pattern_t = r"\b" + re.escape(norm_t) + r"\b"
            for p in predicates:
                val = intent_sql_checker._normalize_sql_value(p.get("value", "")).lower()
                pattern_v = r"\b" + re.escape(val) + r"\b"
                if re.search(pattern_t, val) or (len(val) >= 3 and re.search(pattern_v, norm_t)):
                    return
            # Also check raw where clause for whole word match
            raw_where = re.search(r"\bWHERE\b\s+(.*)", sql, re.IGNORECASE | re.DOTALL)
            if raw_where and re.search(pattern_t, raw_where.group(1).lower()):
                return
    mismatches.append("TARGET_MISMATCH")

intent_sql_checker._check_filter_target = refined_check_filter_target

# 4. In risk_engine, calibrate FIELD_MISMATCH on SELECT
orig_overrides = risk_engine._apply_safety_overrides
def calibrated_overrides(operation, mismatches, scope, impact_level, risk_score):
    is_select = (operation == "SELECT")
    has_field_mm = ("FIELD_MISMATCH" in mismatches)
    
    # We run orig_overrides without FIELD_MISMATCH if SELECT
    mms_to_pass = [m for m in mismatches if not (is_select and m == "FIELD_MISMATCH")]
    score = orig_overrides(operation, mms_to_pass, scope, impact_level, risk_score)
    
    if is_select and has_field_mm:
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

# Run tests
with open("bird_eval/results/bird_fresh_mutations_dataset.json", encoding="utf-8") as f:
    data = json.load(f)

adapter = GuardianBIRDAdapter(disable_llm_intent=True)

# 1. Benign queries (50)
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

benign_decisions = Counter()
blocked_benign = []
for item in clean_cases:
    db_id = item["db_id"]
    db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
    if not db_path.exists():
        matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
        if matches: db_path = matches[0]
    conn = adapter.open_database_connection(db_path, read_only=True)
    res = adapter.evaluate_query(item["q"], item["sql"], connection=conn)
    conn.close()
    benign_decisions[res["decision"]] += 1
    if res["decision"] == "BLOCK":
        blocked_benign.append((item["qid"], item["q"], res["mismatches"]))

print("=" * 60)
print("REFINED CALIBRATED BENIGN RESULTS (50 Clean Queries):")
print(dict(benign_decisions))
if blocked_benign:
    print(f"Blocked {len(blocked_benign)} queries:")
    for b in blocked_benign:
        print(f"  QID {b[0]}: {b[1]} | Mismatches: {b[2]}")
print("=" * 60)

# 2. Fresh Mutations (342)
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

print(f"\nREFINED FRESH MUTATIONS: {mut_correct}/{len(mutations)} ({mut_correct/len(mutations)*100:.2f}%)")
for c, st in sorted(mut_cats.items()):
    acc = st["correct"] / st["total"] * 100
    print(f"  {c:<25}: {st['correct']}/{st['total']} ({acc:.1f}%)")
