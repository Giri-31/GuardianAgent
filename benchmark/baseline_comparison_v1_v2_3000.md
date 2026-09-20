# Baseline Comparison: Always-Allow vs. Rule-Filter vs. GuardianAgent
## Final Evaluation on 3,000 Combined Benchmark Cases (V1 + V2)

**Repository**: `D:\Git\GuardianAgent`  
**Evaluation Date**: 2026-09-20T11:25:13.074348+00:00  
**GuardianAgent Core Status**: **FROZEN & UNMODIFIED**  

---

## 1. Experimental Setup & Dataset Specification

This evaluation performs a strictly apples-to-apples baseline comparison across three methods evaluated on the exact same benchmark datasets:

- **V1 Held-Out Benchmark**: `benchmark/heldout_v1_1500_dataset.json` (1,500 synthetic independent held-out cases)
- **V2 Adversarial Benchmark**: `benchmark/adversarial_v2_1500_dataset.json` (1,500 synthetic adversarial cases)
- **Combined 3,000-Case Suite**: `benchmark/combined_v1_v2_3000.json` (1,500 V1 + 1,500 V2 = 3,000 cases)
- **Dataset Duplication Audit**: 0 exact identical JSON case objects; 488 duplicate `(user_request, SQL)` pairs (preserved transparently without silent filtering).

### Methods Evaluated
1. **Always-Allow**: Blind baseline predicting `ALLOW` for every incoming SQL query without inspection.
2. **Rule-Filter**: Standard heuristic static analyzer inspecting keyword tokens (`DROP TABLE`, `DELETE/UPDATE` without `WHERE`, etc.) as defined in `rule_filter.py`.
3. **GuardianAgent (Full)**: Frozen consequence-aware safety verification engine combining semantic intent analysis, SQL risk scoring, scope analysis, and impact assessment.

---

## 2. Combined V1 + V2 Baseline Comparison (3,000 Cases)

| Method | Cases | Accuracy | Macro-F1 | Unsafe Miss Rate | Safe False-Block Rate | Mean Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Always-Allow** | 3,000 | 41.33% | 0.195 | 100.0% | 0.0% | 0.0 ms |
| **Rule-Filter** | 3,000 | 46.7% | 0.4191 | 67.58% | 0.0% | 0.001 ms |
| **GuardianAgent** | 3,000 | **99.1%** | **0.9884** | **2.25%** | **0.0%** | 0.652 ms |

---

## 3. V1 Held-Out Benchmark Comparison (1,500 Cases)

| Method | Cases | Accuracy | Macro-F1 | Unsafe Miss Rate | Safe False-Block Rate | Mean Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Always-Allow** | 1,500 | 39.33% | 0.1882 | 100.0% | 0.0% | 0.0 ms |
| **Rule-Filter** | 1,500 | 44.2% | 0.4129 | 69.5% | 0.0% | 0.001 ms |
| **GuardianAgent** | 1,500 | **100.0%** | **1.0** | **0.0%** | **0.0%** | 0.638 ms |

---

## 4. V2 Adversarial Benchmark Comparison (1,500 Cases)

| Method | Cases | Accuracy | Macro-F1 | Unsafe Miss Rate | Safe False-Block Rate | Mean Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Always-Allow** | 1,500 | 43.33% | 0.2016 | 100.0% | 0.0% | 0.0 ms |
| **Rule-Filter** | 1,500 | 49.2% | 0.421 | 65.67% | 0.0% | 0.001 ms |
| **GuardianAgent** | 1,500 | **98.2%** | **0.9752** | **4.5%** | **0.0%** | 0.665 ms |

---

## 5. Detailed Per-Class Classification & Safety Metrics

### A. Combined Benchmark (3,000 Cases)

#### GuardianAgent Per-Class Performance:
- **ALLOW**: Precision = 1.0, Recall = 1.0, F1 = 1.0 (Support = 1240)
- **CONFIRM**: Precision = 0.954, Recall = 1.0, F1 = 0.9765 (Support = 560)
- **BLOCK**: Precision = 1.0, Recall = 0.9775, F1 = 0.9886 (Support = 1200)

#### Confusion Matrices (Actual rows × Predicted columns: `[ALLOW, CONFIRM, BLOCK]`):

```
Always-Allow:  [[1240, 0, 0], [560, 0, 0], [1200, 0, 0]]
Rule-Filter:   [[907, 333, 0], [375, 105, 80], [237, 574, 389]]
GuardianAgent: [[1240, 0, 0], [0, 560, 0], [0, 27, 1173]]
```

#### Safety Risk Metrics:
- **Dangerous Cases Total (actual BLOCK)**: 1200
- **GuardianAgent Dangerous Not Blocked (Unsafe Miss)**: 27 (2.25%)
  - Dangerous ALLOW: 0
  - Dangerous CONFIRM: 27
- **Rule-Filter Dangerous Not Blocked**: 811 (67.58%)
- **Always-Allow Dangerous Not Blocked**: 1200 (100.0%)

---

## 6. Verification of Experimental Invariants

- [x] **V1 Case Count**: Exactly 1,500 cases.
- [x] **V2 Case Count**: Exactly 1,500 cases.
- [x] **Combined Benchmark**: Exactly 3,000 cases.
- [x] **Identical Evaluation Suite**: All 3 methods evaluated against identical inputs and labels.
- [x] **GuardianAgent Core Untouched**: `guardian.py`, `risk_engine.py`, etc., were 100% frozen.
- [x] **No Historical Number Reuse**: Baselines and GuardianAgent were executed fresh from end to end.
