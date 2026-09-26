# AST SQL Policy Firewall — Held-Out Evaluation Summary (342 Cases)

**Evaluation Date:** 2026-09-26  
**Artifact:** `heldout_342_results.json`  
**Dataset:** `bird_eval/results/bird_fresh_mutations_dataset.json` (342 held-out BIRD mutations)  
**Firewall Version:** 1.0 (Frozen)  
**SQL Parser:** SQLGlot 30.19.0 (Dialect: `sqlite`)  

---

## 1. Executive Summary

The AST SQL Policy Firewall was evaluated as a deterministic, non-LLM structural security baseline on the frozen 342-case BIRD held-out mutation benchmark.

- **Overall Accuracy / Interception:** 153 / 342 (**44.74%**)
- **Dangerous Miss Rate:** 189 / 342 (**55.26%**)
- **Safety Interception Rate:** 153 / 342 (**44.74%**)
- **Benign False-Block Rate:** 0.0% (0 / 50 clean queries blocked)
- **Parser Failure Rate:** 3 / 342 (**0.88%**) (all 3 intercepted as UNSAFE per fail-closed policy)
- **Mean Latency:** **1.76 ms**
- **Median Latency:** **1.06 ms** (Min: 0.29 ms, Max: 14.86 ms)

---

## 2. Confusion Matrix

| | Predicted SAFE | Predicted UNSAFE | Total Expected |
|---|---:|---:|---:|
| **Expected SAFE** | 0 | 0 | 0 |
| **Expected UNSAFE** | 189 (Dangerous Miss) | 153 (True Interception) | 342 |
| **Total Predicted** | 189 | 153 | 342 |

*Note: All 342 cases in the mutation evaluation suite are adversarial/mutated queries requiring interception (expected decision = BLOCK or CONFIRM).*

---

## 3. Per-Category Breakdown

| Mutation Category | Total Cases | AST Intercepted (UNSAFE) | AST Missed (SAFE) | Interception Rate (%) |
|---|---:|---:|---:|---:|
| `DANGEROUS_DELETE` | 50 | 50 | 0 | **100.00%** |
| `DANGEROUS_DROP` | 50 | 50 | 0 | **100.00%** |
| `DANGEROUS_UPDATE` | 50 | 50 | 0 | **100.00%** |
| `DANGEROUS_DELETE_WHERE` | 50 | 0 | 50 | **0.00%** |
| `TARGET_MISMATCH` | 50 | 0 | 50 | **0.00%** |
| `SCOPE_ESCALATION` | 47 | 2 | 45 | **4.26%** |
| `FIELD_INJECT` | 45 | 1 | 44 | **2.22%** |
| **Total** | **342** | **153** | **189** | **44.74%** |

*Note: The 3 interceptions in `SCOPE_ESCALATION` (2) and `FIELD_INJECT` (1) occurred due to syntax errors / unclosed parentheses in the generated mutations, which triggered the fail-closed parser policy.*

---

## 4. Latency Distribution

| Statistic | Value (ms) |
|---|---:|
| **Mean** | 1.7616 |
| **Median** | 1.0643 |
| **Min** | 0.2938 |
| **Max** | 14.8643 |

---

## 5. Root Cause Analysis of Misses (189 Cases)

All 189 missed cases stem directly from the fundamental limitation of intent-agnostic structural SQL inspection:

1. **`DANGEROUS_DELETE_WHERE` (50 misses):**  
   The SQL is a syntactically valid `DELETE` statement with a `WHERE` clause (e.g. `DELETE FROM orders WHERE order_id = 42;`). Under pure AST inspection with no access to user intent, this is structurally compliant with database safety policies. Only an intent-conditioned gateway can know that the user asked a read inquiry (e.g. *"List all orders"*).
2. **`TARGET_MISMATCH` (50 misses):**  
   The SQL targets an existing, valid table in the schema, but the wrong entity relative to the user query (e.g., querying `customer_archive` instead of `customers`). The AST firewall verifies table existence against schema metadata, finds the table exists, and allows execution.
3. **`SCOPE_ESCALATION` (45 misses):**  
   The SQL contains valid filtering predicates, but relaxes constraints requested by the user. The AST cannot distinguish between requested vs. unrequested WHERE constraints.
4. **`FIELD_INJECT` (44 misses):**  
   The SQL projects additional valid schema columns not requested by the user, exposing sensitive data without triggering any structural or DDL violation.
