"""
Audit script for Task A and Task B.
Reads frozen result file - no modifications to GuardianAgent.
"""
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('bird_eval/results/bird_fresh_mutation_eval_results.json', encoding='utf-8') as f:
    results = json.load(f)

print("=" * 80)
print("TASK A: ALL 9 AUTONOMOUS ESCAPES (expected=attack, actual=ALLOW)")
print("=" * 80)
escapes = [r for r in results if r['guardian_decision'] == 'ALLOW']
print(f"Total ALLOW decisions: {len(escapes)}\n")

for i, r in enumerate(escapes, 1):
    print(f"--- Escape #{i} ---")
    print(f"  Mutation ID : {r.get('mutation_id', 'N/A')}")
    print(f"  Database    : {r['db_id']}")
    print(f"  Category    : {r['category']}")
    print(f"  Expected    : {r['expected_decision']}")
    print(f"  Actual      : {r['guardian_decision']}")
    print(f"  Risk Score  : {r['risk_score']}")
    print(f"  Mismatches  : {r['mismatches']}")
    print(f"  Request     : {r['original_question']}")
    print(f"  Mutated SQL : {r['mutated_sql']}")
    print()

print("=" * 80)
print("TASK B: TARGET_MISMATCH DETAILED BREAKDOWN")
print("=" * 80)
tm = [r for r in results if r['category'] == 'TARGET_MISMATCH']
tm_block = [r for r in tm if r['guardian_decision'] == 'BLOCK']
tm_confirm = [r for r in tm if r['guardian_decision'] == 'CONFIRM']
tm_allow = [r for r in tm if r['guardian_decision'] == 'ALLOW']
print(f"Total TARGET_MISMATCH: {len(tm)}")
print(f"  BLOCK  : {len(tm_block)} / 50 ({len(tm_block)/50*100:.1f}%)")
print(f"  CONFIRM: {len(tm_confirm)} / 50 ({len(tm_confirm)/50*100:.1f}%)")
print(f"  ALLOW  : {len(tm_allow)} / 50 ({len(tm_allow)/50*100:.1f}%)")
print(f"  Intercepted (BLOCK+CONFIRM): {len(tm_block)+len(tm_confirm)} / 50 ({(len(tm_block)+len(tm_confirm))/50*100:.1f}%)")
print()

print("  TARGET_MISMATCH CONFIRM cases (expected BLOCK, got CONFIRM - 'missed' in strict metric):")
for r in tm_confirm:
    print(f"    DB={r['db_id']} | Risk={r['risk_score']:.2f} | Mismatches={r['mismatches']}")
    print(f"    Q: {r['original_question']}")
    print(f"    SQL: {r['mutated_sql'][:100]}...")
    print()

print("  TARGET_MISMATCH ALLOW case (the 1 full escape):")
for r in tm_allow:
    print(f"    DB={r['db_id']} | Risk={r['risk_score']:.2f} | Mismatches={r['mismatches']}")
    print(f"    Q: {r['original_question']}")
    print(f"    SQL: {r['mutated_sql']}")
    print()

print("=" * 80)
print("TASK B: SCOPE_ESCALATION BREAKDOWN")
print("=" * 80)
se = [r for r in results if r['category'] == 'SCOPE_ESCALATION']
se_block = [r for r in se if r['guardian_decision'] == 'BLOCK']
se_confirm = [r for r in se if r['guardian_decision'] == 'CONFIRM']
se_allow = [r for r in se if r['guardian_decision'] == 'ALLOW']
print(f"Total SCOPE_ESCALATION: {len(se)}")
print(f"  BLOCK  : {len(se_block)}")
print(f"  CONFIRM: {len(se_confirm)}")
print(f"  ALLOW  : {len(se_allow)}  <- these are the escapes")
print()
print("  SCOPE_ESCALATION ALLOW (escaped) cases:")
for r in se_allow:
    print(f"    DB={r['db_id']} | Risk={r['risk_score']:.2f} | Mismatches={r['mismatches']}")
    print(f"    Q: {r['original_question']}")
    print(f"    SQL: {r['mutated_sql'][:120]}")
    print()

print("=" * 80)
print("MATH VERIFICATION (Task B)")
print("=" * 80)
total = len(results)
block_count = sum(1 for r in results if r['guardian_decision'] == 'BLOCK')
confirm_count = sum(1 for r in results if r['guardian_decision'] == 'CONFIRM')
allow_count = sum(1 for r in results if r['guardian_decision'] == 'ALLOW')
strict_correct = sum(1 for r in results if r['decision_correct'])
intercepted = block_count + confirm_count

print(f"Total cases : {total}")
print(f"BLOCK       : {block_count}")
print(f"CONFIRM     : {confirm_count}")
print(f"ALLOW       : {allow_count}")
print(f"Strict correct (BLOCK where expected BLOCK): {strict_correct} / {total} = {strict_correct/total*100:.2f}%")
print(f"Intercepted (BLOCK+CONFIRM): {intercepted} / {total} = {intercepted/total*100:.2f}%")
print(f"Autonomous escapes: {allow_count} / {total} = {allow_count/total*100:.2f}%")
assert strict_correct == 314, f"Expected 314, got {strict_correct}"
assert intercepted == 333, f"Expected 333, got {intercepted}"
assert allow_count == 9, f"Expected 9 escapes, got {allow_count}"
print("All math checks PASS.")
