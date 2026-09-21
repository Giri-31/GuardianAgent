import json
from collections import Counter

with open('bird_eval/results/bird_fresh_mutation_eval_results.json', encoding='utf-8') as f:
    results = json.load(f)

misses = [r for r in results if not r['decision_correct']]
print('Total misses:', len(misses))
print('By category:', Counter(r['category'] for r in misses))
print('By guardian decision:', Counter(r['guardian_decision'] for r in misses))

tm_misses = [r for r in misses if r['category'] == 'TARGET_MISMATCH']
print('\nTARGET_MISMATCH decisions:', Counter(r['guardian_decision'] for r in tm_misses))
print('TARGET_MISMATCH mismatches detected:', Counter(str(r['mismatches']) for r in tm_misses))

print('\nExamples of CONFIRM in TARGET_MISMATCH (intercepted, but scored CONFIRM):')
for r in [r for r in tm_misses if r['guardian_decision'] == 'CONFIRM'][:5]:
    print('  DB:', r['db_id'], '| Risk:', r['risk_score'], '| Mismatches:', r['mismatches'])
    print('  Q:', r['original_question'])
    print('  SQL:', r['mutated_sql'][:90])
    print()

print('\nOther misses (FIELD_INJECT / SCOPE_ESCALATION):')
other_misses = [r for r in misses if r['category'] != 'TARGET_MISMATCH']
for r in other_misses:
    print('  Cat:', r['category'], '| DB:', r['db_id'], '| Decision:', r['guardian_decision'], '| Risk:', r['risk_score'])
    print('  Q:', r['original_question'])
    print('  SQL:', r['mutated_sql'][:90])
    print()
