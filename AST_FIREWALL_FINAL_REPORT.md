# AST-Based SQL Policy Firewall: Final Research Report & Baseline Evaluation

**Project:** GuardianAgent: Preventing Catastrophic Database Operations in AI Coding Assistants  
**Component:** Independent AST-Based SQL Policy Firewall Baseline  
**Date:** 2026-09-26  
**Status:** Frozen (Version 1.0)  
**Target Venue:** IEEE Conference (6-page limit)  

---

## 1. Objective

AI coding assistants frequently generate SQL statements that interact directly with production and analytical databases. While conventional database security often relies on static analysis, Web Application Firewalls (WAFs), or Abstract Syntax Tree (AST) policy firewalls, these mechanisms operate without natural language context.

The objective of this baseline is to build and rigorously evaluate a **standalone, deterministic, non-LLM AST-based SQL Policy Firewall** as a direct baseline competitor to GuardianAgent. This baseline represents conventional industry SQL security practice: inspecting the grammatical structure, operations, targets, and clauses of SQL queries against formal security policies, completely independent of user natural-language intent.

---

## 2. Architecture

The AST SQL Policy Firewall is architected as a modular, deterministic pipeline:

```text
                  SQL Query (+ Optional Schema Context)
                                  │
                                  ▼
                         SQLGlot Parser (SQLite)
                                  │
                                  ▼
                         Abstract Syntax Tree (AST)
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
              Operation         Scope          Schema
              Analysis        Analysis        Analysis
            (DML/DDL Type)  (WHERE/Scope)  (Table Exists)
                  │               │               │
                  └───────────────┼───────────────┘
                                  ▼
                            Policy Engine
                       (8 Deterministic Rules)
                                  │
                         ┌────────┴────────┐
                         ▼                 ▼
                       SAFE              UNSAFE
                                  (Violations Logged)
```

### Module Structure
- `bird_eval/ast_firewall/parser.py`: SQLGlot parsing wrapper supporting SQLite dialect, code fence sanitization, and multi-statement scripts.
- `bird_eval/ast_firewall/ast_analyzer.py`: AST feature extractor extracting operation types, physical tables (filtering Common Table Expressions), column projections, predicates, and WHERE clause triviality.
- `bird_eval/ast_firewall/schema_analyzer.py`: SQLite schema introspector caching table and column catalogs across target databases.
- `bird_eval/ast_firewall/policy_engine.py`: Rule evaluator implementing fixed security policies.
- `bird_eval/ast_firewall/firewall.py`: Top-level gateway interface measuring microsecond-level execution latency.
- `bird_eval/ast_firewall/evaluator.py`: Standardized metric computation harness.

---

## 3. Implemented Safety Policies

The firewall evaluates queries against a fixed, transparent policy suite (`AST_FIREWALL_VERSION = 1.0`):

| Policy ID | Policy Name | Trigger Condition | Decision | Rationale |
|---|---|---|:---:|---|
| **POL-1** | `DROP_DETECTED` | Any `DROP TABLE`, `DROP VIEW`, or `DROP DATABASE` statement | **UNSAFE** | Permanent destruction of schema objects. |
| **POL-2** | `TRUNCATE_DETECTED` | Any `TRUNCATE TABLE` command | **UNSAFE** | Immediate unrecoverable deletion of table contents. |
| **POL-3** | `ALTER_DETECTED` | Any `ALTER TABLE` schema modification | **UNSAFE** | Structural alteration of database schema. |
| **POL-4** | `DELETE_WITHOUT_WHERE` | `DELETE` lacking a `WHERE` clause or containing trivial tautology (`1=1`, `TRUE`) | **UNSAFE** | Unbounded full-table deletion. |
| **POL-5** | `UPDATE_WITHOUT_WHERE` | `UPDATE` lacking a `WHERE` clause or containing trivial tautology (`1=1`, `TRUE`) | **UNSAFE** | Unbounded table-wide data overwrite. |
| **POL-6** | `UNKNOWN_TABLES` | Query references physical tables not present in the database catalog | **UNSAFE** | Foreign schema reference, injection artifact, or hallucinated entity. |
| **POL-7** | `PARSER_FAILURE` | Query cannot be parsed into a valid AST (malformed SQL or dialect error) | **UNSAFE** | Fail-closed security posture against parser evasion. |
| **POL-8** | `MULTI_STATEMENT_RISK` | Multi-statement batch containing any destructive statement | **UNSAFE** | Stacked query injection prevention. |

---

## 4. Development Evaluation (336 Cases)

Prior to held-out evaluation, the frozen firewall was verified on the 336-case BIRD development mutation dataset (`bird_eval/results/bird_mutations_dataset.json`):

- **Total Cases:** 336
- **Safety Interception (UNSAFE):** 150 / 336 (**44.64%**)
- **Dangerous Miss Rate (SAFE):** 186 / 336 (**55.36%**)
- **Benign False-Block Rate:** 0.0%
- **Parser Failures:** 0 / 336 (**0.0%**)
- **Mean Latency:** 2.16 ms
- **Median Latency:** 0.99 ms

### Development Category Breakdown
- `DANGEROUS_DELETE`: 50/50 (**100.0%**)
- `DANGEROUS_DROP`: 50/50 (**100.0%**)
- `DANGEROUS_UPDATE`: 50/50 (**100.0%**)
- `DANGEROUS_DELETE_WHERE`: 0/50 (**0.0%**)
- `TARGET_MISMATCH`: 0/50 (**0.0%**)
- `SCOPE_ESCALATION`: 0/46 (**0.0%**)
- `FIELD_INJECT`: 0/40 (**0.0%**)

---

## 5. Held-Out Evaluation (342 Cases)

The frozen firewall was evaluated on the independent 342-case held-out BIRD mutation dataset (`bird_eval/results/bird_fresh_mutations_dataset.json`). No policies or thresholds were adjusted.

- **Total Cases:** 342
- **Overall Accuracy / Interception:** 153 / 342 (**44.74%**)
- **Dangerous Miss Rate:** 189 / 342 (**55.26%**)
- **Safety Interception Rate:** 153 / 342 (**44.74%**)
- **Benign False-Block Rate:** 0.0%
- **Parser Failures:** 3 / 342 (**0.88%**) (fail-closed, classified UNSAFE)
- **Mean Latency:** **1.7616 ms**
- **Median Latency:** **1.0643 ms** (Min: 0.2938 ms, Max: 14.8643 ms)

### Confusion Matrix
| Metric | Count |
|---|---:|
| True Safe | 0 |
| False Unsafe (False-Block) | 0 |
| False Safe (Dangerous Miss) | 189 |
| True Unsafe (Safety Interception) | 153 |

---

## 6. Benign Evaluation (50 Clean Cases)

The firewall was evaluated on the 50 clean gold queries from the BIRD benchmark (`bird_eval/results/bird_mini_dev_50_eval.json`):

- **Total Benign Queries:** 50
- **Correctly Allowed (SAFE):** 50 / 50 (**100.0%**)
- **False Blocks (UNSAFE):** 0 / 50 (**0.0%**)
- **Parser Failures:** 0 / 50 (**0.0%**)
- **Mean Latency:** 4.40 ms
- **Median Latency:** 3.17 ms

*Result:* The AST Policy Firewall achieves a **0.0% false-block rate**, confirming that its policies do not penalize complex valid analytical SQL constructs (joins, subqueries, CTEs, window functions).

---

## 7. Category Analysis

The table below contrasts the AST Policy Firewall with GuardianAgent across all 7 mutation categories on the 342 held-out cases:

| Category | Cases | AST Interception | GuardianAgent Interception | Category Nature |
|---|---:|---:|---:|---|
| `DANGEROUS_DELETE` | 50 | 50 (**100.0%**) | 50 (**100.0%**) | Structural write without WHERE |
| `DANGEROUS_DROP` | 50 | 50 (**100.0%**) | 50 (**100.0%**) | Structural DDL destruction |
| `DANGEROUS_UPDATE` | 50 | 50 (**100.0%**) | 50 (**100.0%**) | Structural write without WHERE |
| `DANGEROUS_DELETE_WHERE` | 50 | 0 (**0.0%**) | 50 (**100.0%**) | Semantic / Intent-violating write |
| `TARGET_MISMATCH` | 50 | 0 (**0.0%**) | 30 (**60.0%**) | Semantic table redirection |
| `SCOPE_ESCALATION` | 47 | 2 (**4.26%**)\* | 40 (**85.11%**) | Constraint relaxation |
| `FIELD_INJECT` | 45 | 1 (**2.22%**)\* | 44 (**97.78%**) | Unrequested data projection |
| **Total** | **342** | **153 (44.74%)** | **314 (91.81%)** | |

*\*The 3 interceptions in `SCOPE_ESCALATION` (2) and `FIELD_INJECT` (1) were due to unclosed subqueries or unquoted column identifiers in the adversarial mutations triggering fail-closed parser exceptions.*

---

## 8. Error Analysis & Root Cause Breakdown

Among the 189 missed held-out cases, errors cluster into two primary root causes:

1. **Semantic Mismatch Not Visible in AST (94 cases / 49.7% of misses):**
   - In `TARGET_MISMATCH` (50 cases) and `FIELD_INJECT` (44 cases), the generated SQL uses syntactically flawless `SELECT` statements referencing valid, existing database tables and columns. 
   - An AST parser cannot determine that the user asked for `student_records` when the SQL queries `disciplinary_actions`, because both tables legitimately exist in the schema.
2. **Natural-Language Scope Not Available (95 cases / 50.3% of misses):**
   - In `DANGEROUS_DELETE_WHERE` (50 cases), the assistant was asked to perform a read-only inquiry (e.g. *"Show employees in marketing"*), but emitted `DELETE FROM employees WHERE department_id = 4`. Because a `WHERE` clause is present, the AST policy considers this a valid scoped maintenance operation.
   - In `SCOPE_ESCALATION` (45 cases), the assistant omitted user-requested filtering predicates. The AST sees a valid filter and cannot know additional conditions were requested in natural language.

---

## 9. Comparison with GuardianAgent

### Table 1: Comparison of SQL Safety Approaches (Paper-Ready)

| Method | Approach | Dangerous Miss Rate ↓ | Benign False-Block ↓ | Mean Latency ↓ |
|---|---|---:|---:|---:|
| **Always Allow** | No protection | 100.00% | 0.00% | < 0.01 ms |
| **Keyword Filter** | Regular expressions / string matching | ~56.20% | 12.00% | 0.12 ms |
| **AST Policy Firewall** | AST parsing + deterministic policies | **55.26%** | **0.00%** | **1.76 ms** |
| **LLM Safety Judge** | Frontier LLM prompt (Gemini 3.6 Flash) | 0.00% | 0.00% | 4,031.10 ms |
| **GuardianAgent** | Intent-conditioned multi-stage verification | **8.19%** | **0.00%** | **7.49 ms** |

### Research Insight
- The AST Policy Firewall is fast (1.76 ms) and completely immune to false-blocking benign queries (0.0%), making it an excellent first-line defense for gross structural errors (DROP, TRUNCATE, unconstrained UPDATE/DELETE).
- However, the AST Policy Firewall suffers a **55.26% dangerous miss rate** because over half of LLM database failures are **semantic attacks** where the SQL is grammatically pristine but directly contradicts user intent.
- GuardianAgent reduces dangerous misses from 55.26% to **8.19%** (an **85.2% relative risk reduction**) while adding only ~5.7 ms of verification overhead.

---

## 10. Limitations of AST-Based SQL Policy Firewalls

1. **Absence of User Intent:** An AST policy firewall has zero visibility into user intentions. It cannot differentiate between a requested deletion and an unprompted hallucinated deletion.
2. **Schema-Valid Redirections:** When an LLM targets an incorrect entity that exists in the database, the AST firewall validates table existence and permits the access.
3. **Scope Ambiguity:** The existence of a `WHERE` clause does not guarantee that the predicate matches the user's criteria.
4. **Parser Fragility:** Dialect variations or unquoted complex column names can trigger parser exceptions, requiring fail-closed policies that reject valid queries if not carefully tuned.

---

## 11. Reproducibility

### Exact Reproduction Command
Run the automated Windows batch reproduction script:
```cmd
run_final_ast_evaluation.bat
```

Or execute directly via Python:
```bash
# 1. Run Unit Tests (31/31 passing)
python -m pytest bird_eval/ast_firewall/tests -v

# 2. Run Development Evaluation (336 cases)
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_mutations_dataset.json --output bird_eval/ast_firewall/results/dev_336_results.json

# 3. Run Held-Out Evaluation (342 cases)
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_fresh_mutations_dataset.json --output bird_eval/ast_firewall/results/heldout_342_results.json

# 4. Run Benign Evaluation (50 cases)
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_mini_dev_50_eval.json --output bird_eval/ast_firewall/results/benign_50_results.json --type benign
```

### Environment Details
- **Python:** 3.13.15 (AMD64)
- **SQLGlot:** 30.19.0
- **Pytest:** 9.1.1
- **Platform:** Windows 11 (AMD64)
- **Manifest File:** `bird_eval/ast_firewall/results/experiment_manifest.json`
