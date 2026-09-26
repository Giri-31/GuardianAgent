# GuardianAgent Experimental Reproduction Guide

This guide provides complete instructions to reproduce every experimental result, benchmark table, and ablation reported in the paper:

> **GuardianAgent: Preventing Catastrophic Database Operations in AI Coding Assistants**

---

## 1. Environment & Prerequisites

### Hardware & Operating System
- Evaluated on: Windows 11 (AMD64)
- Also verified on: Linux (Ubuntu 22.04 LTS / Debian)

### Python Environment
- Python Version: **3.13.15** (Python 3.10+ supported)
- Virtual Environment recommended:
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### Dependencies
Install exact frozen dependencies:
```bash
pip install sqlglot==30.19.0 pytest==9.1.1
```

---

## 2. Environment Variables

GuardianAgent operates in deterministic, reproducible mode without external non-deterministic LLM API calls:

```cmd
:: Windows Command Prompt
set GUARDIAN_DISABLE_LLM=1
set GUARDIAN_READ_SAFETY_LEVEL=STRICT

# Linux / Bash
export GUARDIAN_DISABLE_LLM=1
export GUARDIAN_READ_SAFETY_LEVEL=STRICT
```

---

## 3. Step-by-Step Reproduction Commands

### Step 1: Controlled Regression Tests (39/39 passing)
Verifies core pipeline regression invariants:
```bash
python controlled_tests.py
```
*Expected Output:* `SUMMARY: Total tests: 39, Correct: 39, Accuracy: 100.0 %`

### Step 2: Primary Held-Out Evaluation (342 BIRD Mutations)
Evaluates GuardianAgent across 10 unseen BIRD databases:
```bash
python bird_eval/scripts/run_fresh_mutation_eval.py
```
*Outputs Generated:*
- `bird_eval/results/bird_fresh_mutation_eval_results.json`
- `bird_eval/results/bird_fresh_mutation_eval_summary.json`  
*Expected Output:* `Strict Policy Match: 314 / 342 (91.81%)`, `Safety Interception: 333 / 342 (97.37%)`, `Catastrophic Defense: 200 / 200 (100.0%)`, `Autonomous Escapes: 9 / 342 (2.63%)`.

### Step 3: Benign Query Evaluation (50 Clean BIRD Queries)
Evaluates false-alarm and interruption rate on harmless queries:
```bash
python bird_eval/scripts/evaluate_benign_queries.py
```
*Outputs Generated:*
- `bird_eval/results/bird_fresh_benign_eval_results.json`  
*Expected Output:* `ALLOW: 31 (62.0%)`, `CONFIRM: 19 (38.0%)`, `False BLOCK: 0 (0.0%)`.

### Step 4: Component Ablation Study (342 Mutations)
Decomposes pipeline into dumb blocklist vs. pure scoring vs. full system:
```bash
python benchmark/run_ablation_study.py
```
*Outputs Generated:*
- `benchmark/ablation_study_results.json`  
*Expected Output:* `Dumb Blocklist: 150/342 (43.9%)`, `Pure Scoring: 342/342 (100.0%)*`, `Full System: 314/342 (91.8%)`.

### Step 5: AST Policy Firewall Baseline
Runs unit tests and evaluation for the deterministic AST baseline:
```bash
# Windows automated batch reproduction:
run_final_ast_evaluation.bat

# Or direct commands:
python -m pytest bird_eval/ast_firewall/tests -v
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_fresh_mutations_dataset.json --output bird_eval/ast_firewall/results/heldout_342_results.json
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_mini_dev_50_eval.json --output bird_eval/ast_firewall/results/benign_50_results.json --type benign
```
*Expected Output:* 31/31 unit tests pass. Held-out interception: 153/342 (44.74%). Benign false-block: 0/50 (0.0%).

### Step 6: Regenerate Paper Tables & Manifests
```bash
python evaluation/generate_manifest.py
python evaluation/generate_comparison_files.py
python evaluation/tables/generate_tables.py
python evaluation/error_analysis/generate_escapes.py
```

---

## 4. Verification Checksums

Verify input dataset integrity using SHA-256:
- `bird_eval/results/bird_fresh_mutations_dataset.json`: matches hash in `evaluation/final_experiment_manifest.json`
- `bird_eval/results/bird_mini_dev_50_eval.json`: matches hash in `evaluation/final_experiment_manifest.json`
- `bird_eval/results/bird_mutations_dataset.json`: matches hash in `evaluation/final_experiment_manifest.json`
