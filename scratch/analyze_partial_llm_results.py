"""
analyze_partial_llm_results.py
Reads the partial LLM judge log to compute running statistics.
"""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

log_path = r"C:\Users\Lenovo\.gemini\antigravity-ide\brain\9f80b53d-5d61-4ecc-b48a-77a7f205943b\.system_generated\tasks\task-736.log"

with open(log_path, encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

# Parse rows: "186  formula_1  FIELD_INJECT  CONFIRM  ALLOW  7047  OK"
pattern = re.compile(
    r'^\s*(\d+)\s+(\S+)\s+(\S+)\s+(BLOCK|CONFIRM|ALLOW)\s+(BLOCK|CONFIRM|ALLOW)\s+(\d+)\s+(OK|FAIL)'
)

rows = []
for line in lines:
    m = pattern.match(line)
    if m:
        rows.append({
            'case': int(m.group(1)),
            'db': m.group(2),
            'cat': m.group(3),
            'expected': m.group(4),
            'llm': m.group(5),
            'ms': int(m.group(6)),
            'ok': m.group(7) == 'OK',
        })

total = len(rows)
correct = sum(1 for r in rows if r['ok'])
block_decisions = sum(1 for r in rows if r['llm'] == 'BLOCK')
allow_decisions = sum(1 for r in rows if r['llm'] == 'ALLOW')

# Dangerous miss rate: expected BLOCK, got ALLOW
block_expected = [r for r in rows if r['expected'] == 'BLOCK']
dangerous_misses = [r for r in block_expected if r['llm'] == 'ALLOW']

# Phase analysis: first 130 vs 131+
early = [r for r in rows if r['case'] <= 130]
late = [r for r in rows if r['case'] > 130]

print(f"=== PARTIAL LLM JUDGE ANALYSIS ({total} cases logged) ===\n")
print(f"Correct        : {correct}/{total} ({correct/total*100:.1f}%)")
print(f"BLOCK decisions: {block_decisions} ({block_decisions/total*100:.1f}%)")
print(f"ALLOW decisions: {allow_decisions} ({allow_decisions/total*100:.1f}%)")
print(f"Dangerous miss : {len(dangerous_misses)}/{len(block_expected)} ({len(dangerous_misses)/len(block_expected)*100:.1f}%)")
print(f"Mean latency   : {sum(r['ms'] for r in rows)/total:.0f} ms")
print()
print(f"=== PHASE ANALYSIS ===")
print(f"Cases 1-130 (early): {sum(1 for r in early if r['ok'])}/{len(early)} correct ({sum(1 for r in early if r['ok'])/len(early)*100:.1f}%)")
early_lat = sum(r['ms'] for r in early)/len(early) if early else 0
late_lat = sum(r['ms'] for r in late)/len(late) if late else 0
print(f"  Mean latency: {early_lat:.0f} ms")
print(f"Cases 131+ (rate-throttled): {sum(1 for r in late if r['ok'])}/{len(late)} correct ({sum(1 for r in late if r['ok'])/len(late)*100:.1f}%)")
print(f"  Mean latency: {late_lat:.0f} ms")
print()

# Per-category
from collections import defaultdict
cat_stats = defaultdict(lambda: {'total': 0, 'correct': 0, 'block': 0, 'allow': 0})
for r in rows:
    cat_stats[r['cat']]['total'] += 1
    if r['ok']:
        cat_stats[r['cat']]['correct'] += 1
    if r['llm'] == 'BLOCK':
        cat_stats[r['cat']]['block'] += 1
    else:
        cat_stats[r['cat']]['allow'] += 1

print("=== PER CATEGORY (partial) ===")
for cat, s in sorted(cat_stats.items()):
    t = s['total']
    acc = s['correct']/t*100 if t > 0 else 0
    print(f"  {cat:<30}: {s['correct']}/{t} ({acc:.0f}%) | BLOCK={s['block']} ALLOW={s['allow']}")

print()
print("=== RATE LIMIT SIGNATURE ===")
# Look for runs of exactly 7000ms ± 200ms
throttled = [r for r in rows if 6800 <= r['ms'] <= 7300]
print(f"Calls with ~7s latency (throttled): {len(throttled)} / {total} ({len(throttled)/total*100:.1f}%)")
print(f"All throttled ALLOW: {sum(1 for r in throttled if r['llm'] == 'ALLOW')}")
print(f"All throttled BLOCK: {sum(1 for r in throttled if r['llm'] == 'BLOCK')}")
