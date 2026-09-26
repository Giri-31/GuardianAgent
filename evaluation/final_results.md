# GuardianAgent — Final Frozen Benchmark Results

**Date:** 2026-09-26  
**Pipeline Version:** Calibrated Production Engine (Frozen v2.0)  
**Target Venue:** IEEE Conference (6-Page Limit)  
**Git State:** Frozen main branch  

---

## 1. System Configuration & Evaluation Invariants

- **Execution Environment:** Windows 11 AMD64, Python 3.13.15, SQLite 3.50.4, SQLGlot 30.19.0.
- **Environment Flags:** `GUARDIAN_DISABLE_LLM=1`, `GUARDIAN_READ_SAFETY_LEVEL=STRICT`.
- **Risk Formula:**  
  $$R = 0.20 \cdot S_{\text{operation}} + 0.40 \cdot S_{\text{mismatch}} + 0.25 \cdot S_{\text{scope}} + 0.15 \cdot S_{\text{impact}}$$
- **Operational Thresholds:**
  - $R < 3.00$: `ALLOW` (Autonomous Execution)
  - $3.00 \le R < 7.00$: `CONFIRM` (Mandatory Human In-the-Loop Review)
  - $R \ge 7.00$: `BLOCK` (Autonomous Immediate Abort)
- **Safety Overrides:** Deterministic blocking on `DROP`, `TRUNCATE`, `ALTER`, unconstrained `DELETE`/`UPDATE`, and cross-table modifications (`DANGEROUS_DELETE_WHERE`). Unprojected read field mismatches demoted to `CONFIRM` (`4.00`). Target entity mismatches in `STRICT` mode enforced as `BLOCK` (`7.00`).

---

## 2. Primary Generalization Result: 342 Held-Out BIRD Mutations

Evaluated on 342 adversarial queries across 10 completely unseen databases from the BIRD benchmark (`bird_eval/results/bird_fresh_mutations_dataset.json`):

| Metric | Measured Value | Theoretical / Baseline Context |
|---|---:|---|
| **Total Test Cases** | **342** | 10 unseen real-world schemas |
| **Strict BLOCK Accuracy** | **314 / 342 (91.81%)** | Exact match with expected policy action |
| **Safety Interception Rate** | **333 / 342 (97.37%)** | Halts autonomous execution (`BLOCK` + `CONFIRM`) |
| **Dangerous Miss Rate** | **9 / 342 (2.63%)** | Erroneously classified as autonomous `ALLOW` |
| **Catastrophic Write Escapes** | **0 / 200 (0.00%)** | 100.0% defense against destructive modifications |
| **Decision Distribution** | `BLOCK`: 246 (71.93%)<br>`CONFIRM`: 87 (25.44%)<br>`ALLOW`: 9 (2.63%) | Only 2.63% autonomous escape rate |

### Per-Category Breakdown (342 Held-Out Cases)

| Mutation Category | Total Cases | Strict Correct | Strict Accuracy (%) | Safety Intercepted | Escaped | Interception Rate (%) |
|---|---:|---:|---:|---:|---:|---:|
| `DANGEROUS_DELETE` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `DANGEROUS_DELETE_WHERE` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `DANGEROUS_DROP` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `DANGEROUS_UPDATE` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `FIELD_INJECT` | 45 | 44 | 97.78% | 45 | 0 | **100.00%** |
| `SCOPE_ESCALATION` | 47 | 40 | 85.11% | 40 | 7 | **85.11%** |
| `TARGET_MISMATCH` | 50 | 30 | 60.00% | 49 | 1 | **98.00%** |
| **Total** | **342** | **314** | **91.81%** | **333** | **9** | **97.37%** |

---

## 3. Benign Query Evaluation: 50 Real BIRD Queries

Evaluated on 50 clean gold queries across the exact same 10 held-out schemas to measure false alarms and developer disruption:

| Metric | Pre-Calibration Baseline | Post-Calibration Final | Impact |
|---|---:|---:|---|
| **Direct Autonomous ALLOW** | 17 / 50 (34.00%) | **31 / 50 (62.00%)** | +28.0% absolute throughput gain |
| **Human Review (CONFIRM)** | 9 / 50 (18.00%) | **19 / 50 (38.00%)** | Non-destructive queries require human sign-off |
| **False BLOCK Rate** | 24 / 50 (48.00%) | **0 / 50 (0.00%)** | **0% false-block rate on evaluated benign set** |
| **Total Interruption Rate** | 33 / 50 (66.00%) | **19 / 50 (38.00%)** | Halved unnecessary disruptions |
| **Mean Latency** | 0.33 ms | **17.38 ms** | Fast sub-20ms inline safety gateway |

---

## 4. Component Ablation Study (342 Cases)

Decomposes GuardianAgent into its constituent layers to isolate source of safety intelligence:

| Configuration Variant | Overall Interception (342 Cases) | Semantic Attacks Only (142 Cases) | Architectural Takeaway |
|---|---:|---:|---|
| **Dumb Keyword Blocklist** | 150 / 342 (43.86%) | 0 / 142 (0.00%) | Completely blind to all subtle semantic attacks |
| **Pure Consequence Scoring\*** | 342 / 342 (100.00%)\* | 142 / 142 (100.00%)\* | Multi-attribute scoring detects all semantic divergence |
| **Full Calibrated System** | **333 / 342 (97.37%)** | **133 / 142 (93.66%)** | Balances autonomy, overrides, and human confirmation |

*\*Note on Ablation Methodology: Under the ablation criterion, cases requiring human confirmation (`CONFIRM`) count as successful interceptions since autonomous execution was halted.*

---

## 5. End-to-End Multi-Turn Agent Evaluation: DBBench (60 Tasks)

Evaluates GuardianAgent integrated inline with an active database agent executing multi-turn workflows:

- **Total Agent Tasks:** 60
- **Correct Tasks Completed:** 46 / 60 (**76.67%**)
- **Safety Invariant Violations:** **0**
- **Dangerous SQL Escapes:** **0**
- **Gateway Decisions:** `ALLOW`: 8 (13.33%), `CONFIRM`: 8 (13.33%), `BLOCK`: 44 (73.33%)
- **Human Intervention Rate:** **13.33%** (8 / 60)
- **Mean Processing Latency:** **2.49 ms** (Median: 1.82 ms, Min: 0.78 ms, Max: 19.15 ms)

---

## 6. Controlled Regression Suite (39 Tests)

- **Total Controlled Unit Tests:** 39
- **Passed:** 39 / 39 (**100.00%**)
- **Purpose:** Verifies behavioral stability and zero-regression status of the core Python rules across updates.
