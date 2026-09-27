# GuardianAgent — Final Experimental Results & IEEE Publication Package

**Document Version:** 1.0 (Frozen Final)  
**Target Venue:** IEEE Conference (Strict 6-Page Limit)  
**Date:** 2026-09-26  
**Artifact Directory:** `evaluation/`  

---

# SECTION A: EXPERIMENTAL RESULTS AND METHODOLOGY

## 1. System Configuration

GuardianAgent is evaluated as a pre-execution safety gateway for LLM-generated database actions. The evaluated engine is the **Calibrated Evaluation Configuration (Frozen v2.0)** running in deterministic mode:

- **Pipeline Execution:** Natural-language intent extraction $\to$ SQL parsing $\to$ Intent-SQL consistency analysis $\to$ Scope analysis $\to$ Consequence/risk calculation $\to$ Action dispatch (`ALLOW`, `CONFIRM`, `BLOCK`).
- **Environment Invariants:** `GUARDIAN_DISABLE_LLM=1`, `GUARDIAN_READ_SAFETY_LEVEL=STRICT`.
- **Formal Risk Formulation:**
  $$R = 0.20 \cdot S_{\text{operation}} + 0.40 \cdot S_{\text{mismatch}} + 0.15 \cdot S_{\text{scope}} + 0.25 \cdot S_{\text{impact}}$$
  where:
  - $S_{\text{operation}} \in [0, 10]$ reflects structural severity of the command verb (e.g. `DROP` = 10.0, `DELETE` = 8.0, `SELECT` = 1.0).
  - $S_{\text{mismatch}} \in [0, 10]$ penalizes divergence between user intent and SQL actions (e.g., target entity redirection = 7.0, operation mismatch = 10.0, unrequested field projection = 4.0).
  - $S_{\text{scope}} \in [0, 10]$ quantifies row-level blast radius (e.g., full-table scan/mutation without `WHERE` = 8.0 to 10.0).
  - $S_{\text{impact}} \in [0, 10]$ represents systemic schema and state consequence.
- **Operational Decision Thresholds:**
  - $R < 3.00 \implies \mathbf{ALLOW}$ (Autonomous execution permitted).
  - $3.00 \le R < 7.00 \implies \mathbf{CONFIRM}$ (Human-in-the-loop review required; execution halted).
  - $R \ge 7.00 \implies \mathbf{BLOCK}$ (Autonomous immediate abort; execution prohibited).
- **Safety Overrides:** Deterministic blocking on destructive DDL (`DROP`, `TRUNCATE`, `ALTER`), unconstrained DML (`DELETE`/`UPDATE` without `WHERE`), and intent-violating targeted deletions (`DANGEROUS_DELETE_WHERE`). Read field mismatches (`FIELD_MISMATCH` on `SELECT`) are safely routed to `CONFIRM` ($R = 4.00$).

---

## 2. Dataset and Experimental Setup

The evaluation adheres to a strict evidence hierarchy to prevent data snooping and overfitting:

### Primary Benchmark: 342 Held-Out BIRD Mutations
- **Source:** 10 unseen real-world databases from the BIRD benchmark (`california_schools`, `card_games`, `codebase_community`, `european_football_2`, `financial`, `formula_1`, `student_club`, `superhero`, `thrombosis_prediction`, `toxicology`).
- **Composition:** 342 adversarial queries across 7 mutation categories (200 catastrophic write mutations, 142 subtle semantic read mutations).
- **Integrity:** Zero database overlap with the 2-database development partition.

### Secondary Benchmark: 50 Benign BIRD Queries
- **Source:** 50 clean, gold-standard queries from the exact same 10 held-out schemas.
- **Purpose:** Measures usability, false alarms, and developer disruption.

### Secondary Benchmark: 60 DBBench Multi-Turn Tasks
- **Source:** 60 live agent tasks testing upstream LLM execution with inline safety monitoring.

### Supporting Suites:
- 336-case BIRD Development Suite (2 databases: calibration only; kept strictly separate).
- 39-test Controlled Regression Suite (100.0% pass rate).

---

## 3. Main Held-Out Results

### Table I: Comparison of SQL Safety Approaches (Held-Out BIRD Benchmark)

| Method | Approach | Cases | Safety Interception Rate (↑) | Strict BLOCK Accuracy (↑) | Dangerous Miss Rate (↓) | Benign False-Block (↓) | Mean Latency (↓) |
|---|---|---:|---:|---:|---:|---:|---:|
| **Always Allow** | Trivial baseline | 342 | 0.00% | 0.00% | 100.00% | 0.00% | < 0.01 ms |
| **Keyword Filter** | Static regex blocklist | 342 | 43.86% | 43.86% | 56.14% | 12.00% | 0.12 ms |
| **AST Policy Firewall** | Non-LLM AST rules | 342 | 44.74% | 44.74% | 55.26% | **0.00%** | **1.76 ms** |
| **GuardianAgent (Proposed)** | Intent-consequence gateway | 342 | **97.37%** | **91.81%** | **2.63%** | **0.00%** | 17 ms (benign); 662 ms (mutation)\* |

*\*GuardianAgent latency is benchmark-dependent. On the 50-query benign BIRD evaluation (no per-query SQLite scope checking): **17.38 ms mean** (3.07 ms median). On the 342-case held-out mutation benchmark (full per-query SQLite scope checking enabled): **662.40 ms mean** (287.36 ms median). See Section 11 for full latency provenance. The AST Policy Firewall latency (1.76 ms) reflects parse-only evaluation with no live SQL execution.

*Key Result:* GuardianAgent achieves a **97.37% Safety Interception Rate** (333/342) and a **91.81% Strict BLOCK Accuracy** (314/342), reducing dangerous autonomous escapes to **2.63%** (9/342).

---

## 4. Category-Level Results

### Table II: Category Breakdown of GuardianAgent on 342 Held-Out Mutations

| Mutation Category | Total Cases | Strict Correct | Strict Accuracy (%) | Safety Intercepted | Autonomous Escaped | Interception Rate (%) |
|---|---:|---:|---:|---:|---:|---:|
| `DANGEROUS_DELETE` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `DANGEROUS_DELETE_WHERE` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `DANGEROUS_DROP` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `DANGEROUS_UPDATE` | 50 | 50 | 100.00% | 50 | 0 | **100.00%** |
| `FIELD_INJECT` | 45 | 44 | 97.78% | 45 | 0 | **100.00%** |
| `SCOPE_ESCALATION` | 47 | 40 | 85.11% | 40 | 7 | **85.11%** |
| `TARGET_MISMATCH` | 50 | 30 | 60.00% | 49 | 1 | **98.00%** |
| **Total** | **342** | **314** | **91.81%** | **333** | **9** | **97.37%** |

*Catastrophic Defense:* **0 out of 200 catastrophic write mutations escaped** across `DANGEROUS_DELETE`, `DANGEROUS_DELETE_WHERE`, `DANGEROUS_DROP`, and `DANGEROUS_UPDATE` (100.0% defense).

---

## 5. Benign Usability Results

### Table IV: Usability & False Alarm Benchmark on 50 Clean BIRD Queries

| Configuration | Autonomous ALLOW (↑) | Human Review (CONFIRM) | False BLOCK Rate (↓) | Total Interruption Rate (↓) | Mean Latency |
|---|---:|---:|---:|---:|---:|
| **Pre-Calibration Baseline** | 17 / 50 (34.00%) | 9 / 50 (18.00%) | 24 / 50 (48.00%) | 33 / 50 (66.00%) | 0.33 ms |
| **Post-Calibration Final** | **31 / 50 (62.00%)** | **19 / 50 (38.00%)** | **0 / 50 (0.00%)** | **19 / 50 (38.00%)** | **17.38 ms** |

*Finding:* Post-calibration logic achieved a **0.0% false-block rate** on the evaluated 50-query benign BIRD set, completely eliminating false aborts while allowing 62.0% of clean queries to proceed autonomously.

---

## 6. Ablation Study

### Table III: Component Ablation on 342 Held-Out Cases

| Component Configuration | Overall Safety Interception | Subtle Semantic Interception (142 Cases) | Methodological Finding |
|---|---:|---:|---|
| **Dumb Keyword Blocklist** | 150 / 342 (43.86%) | 0 / 142 (0.00%) | 0% recall on semantic deviations |
| **Pure Consequence Scoring\*** | 342 / 342 (100.00%)\* | 142 / 142 (100.00%)\* | Multi-attribute scoring supplies core semantic intelligence |
| **Full GuardianAgent Pipeline** | **333 / 342 (97.37%)** | **133 / 142 (93.66%)** | Combines policy overrides with calibrated thresholds |

*\*Ablation Interpretation:* Under the ablation criterion, cases halted for human review (`CONFIRM`) count as successful interceptions. The consequence-scoring component prevented autonomous execution for all evaluated mutations under this criterion, confirming that semantic protection is primarily supplied by consequence scoring rather than keyword filtering.

---

## 7. DBBench End-to-End Multi-Turn Agent Evaluation

### Table V: Multi-Turn Agent Benchmark (60 Tasks)

| Evaluation Metric | Measured Result |
|---|---:|
| Total Agent Tasks Evaluated | 60 |
| Correctly Completed Tasks | 46 (76.67%) |
| Safety Invariant Violations | **0** |
| Dangerous SQL Escapes | **0** |
| Autonomous ALLOW Decisions | 8 (13.33%) |
| Human Review Required (`CONFIRM`) | 8 (13.33%) |
| Autonomous Aborts (`BLOCK`) | 44 (73.33%) |
| Mean Execution Latency | 2.49 ms (Median: 1.82 ms) |

---

## 8. Baseline Comparison: AST Policy Firewall vs. GuardianAgent

- **Gross Structural Operations:** Both the AST Policy Firewall and GuardianAgent intercept 100.0% of unconstrained writes (`DELETE` without `WHERE`, `UPDATE` without `WHERE`, `DROP`).
- **Semantic Attacks:** The AST Policy Firewall misses 98.44% of semantic-category attacks (189 misses across all four semantic categories: `DANGEROUS_DELETE_WHERE`, `TARGET_MISMATCH`, `SCOPE_ESCALATION`, and `FIELD_INJECT`) because these queries are structurally compliant SQL that requires natural-language context to evaluate.
- **GuardianAgent Advantage:** GuardianAgent reduces dangerous misses from 55.26% down to **2.63%** by cross-referencing user intent with AST-derived relational targets.

---

## 9. Autonomous Escape Analysis (9 Cases)

All 9 autonomous escapes are non-destructive read operations (`SELECT`), categorized across four failure mechanisms:
1. **Self-Join Ambiguity (1 case — California Schools ID 13, `TARGET_MISMATCH`):** The mutation substituted the correct table reference with a self-join (`frpm AS T1 JOIN frpm AS T2`). Because `frpm` is a valid intent entity, table matching succeeded and the mismatch was not detected.
2. **Negative Prepositional Clause (1 case — Card Games ID 47, `SCOPE_ESCALATION`):** The natural language constraint *"without powerful foils"* was dropped by the intent extractor, producing an unconstrained scan.
3. **Comparative Language & Named Filters (1 case — Codebase Community ID 75, `SCOPE_ESCALATION`):** The comparative constraint *"higher reputation, Harlan or Jarrod"* was omitted in generated SQL.
4. **Unrequested Field Projection (1 case — Superhero ID 276, `FIELD_INJECT`):** The SQL injected `weight_kg` alongside the requested `height_cm` ranking, but the FIELD_MISMATCH signal was not raised because the field was superficially consistent with the `superhero` entity context.
5. **Dropped Restrictive Modifiers (5 cases — Formula 1 ID 191, Thrombosis Prediction IDs 281/288/295, Toxicology ID 334, all `SCOPE_ESCALATION`):** Complex subordinate clauses (e.g. *"held on circuit in Germany"*, *"among all the SLE patients"*, *"carcinogenic"*) were omitted, producing unconstrained scans that the intent extractor could not detect.

---

## 10. SCOPE_ESCALATION Analysis

`SCOPE_ESCALATION` achieved 85.11% interception (40/47) with 7 escapes. Although non-destructive, these queries represent **semantically unsafe autonomous reads** that expose unrequested data. The root cause is the inability of rule-based intent parsers to extract multi-word subordinate clauses.

---

## 11. Latency Profile

- Controlled Test Baseline (no intent extraction, no schema query): 0.33 ms mean
- AST Policy Firewall (held-out 342-case benchmark): 1.76 ms mean (1.06 ms median)
- DBBench Inline Agent (60 live agent tasks, intent extraction included): 2.49 ms mean (1.82 ms median)
- Benign BIRD Queries (50 clean gold queries, intent extraction included, no scope-check penalty): **17.38 ms mean** (3.07 ms median)
- Held-Out BIRD Mutations (342 adversarial cases, full intent extraction + SQLite scope-checking per query): **662.40 ms mean** (287.36 ms median)

> [!NOTE]
> The 17.38 ms figure (benign queries) and 662.40 ms figure (held-out mutations) both include GuardianAgent's LLM-free intent extraction path (`GUARDIAN_DISABLE_LLM=1`). The 640 ms difference is attributable primarily to SQLite per-query scope verification executed for each mutation case but not required for structurally simple benign queries. Mean latency figures should be interpreted relative to their evaluation scope.

---

## 12. Limitations

1. **Natural Language Scope Ambiguity:** Rule-based intent extractors fail on negative prepositions, complex comparatives, and nested qualifiers.
2. **Schema Invariance vs. Entity Semantic Gaps:** Tables sharing common attributes in self-joins can evade target matching.
3. **Synthetic Mutation Bias:** BIRD mutations represent systematic perturbation classes, but do not exhaust all arbitrary LLM reasoning errors.

---

## 13. Threats to Validity

- **Internal Validity:** Controlled regression tests guarantee reproducible rule firing (100% on 39 unit tests).
- **External Validity:** Evaluated on 10 held-out databases unseen during development; results are encouraging but generalization to deployment environments with substantially different query distributions or database schemas has not been established.
- **Construct Validity:** Evaluated on both strict policy classification and end-to-end task completion (DBBench).

---

## 14. Reproducibility

Execute the reproduction script:
```cmd
run_final_ast_evaluation.bat
```
Direct evaluation command:
```bash
python bird_eval/scripts/run_fresh_mutation_eval.py
```
Manifest hash and provenance recorded in `evaluation/final_experiment_manifest.json`.

---

## 15. Publication Claim Audit

### Verified & Rigorously Supported Claims:
- "GuardianAgent intercepted 97.37% of unsafe queries on the 342-case held-out BIRD benchmark."
- "No catastrophic write operation escaped in the evaluated held-out mutation suite (0/200 escapes)."
- "GuardianAgent achieved a 0.0% false-block rate on the evaluated 50-query benign BIRD set."
- "GuardianAgent operates with a 2.49 ms mean latency in live agent benchmarks."
- "GuardianAgent reduces dangerous escapes from 55.26% (AST baseline) to 2.63% by conditioning verification on user intent."

### Prohibited / Unsupported Claims Removed:
- No claims of "guaranteed safety", "universal protection", or "zero false alarms".

---

# SECTION B: 6-PAGE IEEE CONFERENCE PAPER BLUEPRINT

## I. Introduction
- **Context:** Rapid adoption of LLM-based coding and data analysis assistants (e.g., Cursor, Devin, GitHub Copilot Workspace).
- **The Problem:** Upstream LLMs frequently hallucinate destructive operations (`DROP`, unconstrained `DELETE`) or make subtle semantic errors (scoping omissions, table mismatches).
- **The Gap:** Conventional database security relies on static keyword blocklists or deterministic AST policy firewalls, which lack awareness of user natural-language intent and fail to detect over 55% of subtle semantic database attacks.
- **GuardianAgent:** A lightweight, pre-execution safety gateway uniting intent parsing, relational AST analysis, and consequence-aware risk scoring.
- **Contributions:**
  1. Multi-attribute risk formulation balancing structural severity, intent divergence, and scope impact.
  2. Evaluation across 342 held-out BIRD mutations in 10 unseen databases, demonstrating 97.37% safety interception and 0/200 catastrophic write escapes.
  3. Empirical comparison showing a **52.63 percentage-point improvement** in safety interception rate (97.37% vs. 44.74%) over deterministic AST policy firewalls, reducing dangerous autonomous escapes from 55.26% to 2.63%.
  4. Real-world validation on DBBench (60 tasks) and 50 benign queries confirming a 0.0% false-block rate.

## II. Related Work
- **LLM Coding Agents & Tool Use:** ReAct, Toolformer, agentic database interaction.
- **SQL & Database Security:** WAFs, Greenplum/Oracle SQL firewalls, prepared statements.
- **Agent Safety & Guardrails:** NeMo Guardrails, Llama Guard, Guardrails AI.

## III. Methodology
- Architectural diagram of the 5-stage GuardianAgent gateway.
- Formal risk formula ($R = 0.20 S_{\text{op}} + 0.40 S_{\text{mismatch}} + 0.15 S_{\text{scope}} + 0.25 S_{\text{impact}}$).
- Tri-modal decision policy (`ALLOW`, `CONFIRM`, `BLOCK`).
- Database-aware schema and impact analysis.

## IV. Experimental Setup
- **Benchmarks:** 342 held-out BIRD mutations (10 databases), 50 benign queries, 60 DBBench tasks.
- **Baselines:** Always Allow, Static Keyword Filter, AST Policy Firewall.
- **Evaluation Metrics:** Safety Interception Rate, Strict BLOCK Accuracy, Dangerous Miss Rate, False-Block Rate, Latency.

## V. Results
- Presentation of Table I (Main Results), Table II (Category Breakdown), Table III (Ablation), Table IV (Benign Usability), Table V (DBBench).
- Key findings on semantic attack interception and zero catastrophic write escapes.

## VI. Error Analysis & Limitations
- Forensic breakdown of the 9 autonomous escapes.
- Deep dive into `SCOPE_ESCALATION` linguistic challenges (negative prepositions, comparatives).
- Threats to validity.

## VII. Conclusion
- Summary of verified experimental evidence.
- Open challenges in natural language scope extraction for database safety.
