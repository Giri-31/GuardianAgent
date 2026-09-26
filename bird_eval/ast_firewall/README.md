# AST-Based SQL Policy Firewall Baseline

This package provides a **deterministic, non-LLM, AST-based SQL Policy Firewall** developed as an independent baseline competitor to GuardianAgent for the IEEE research paper:

> **GuardianAgent: Preventing Catastrophic Database Operations in AI Coding Assistants**

## Architecture

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
```

## Structure

```text
bird_eval/ast_firewall/
├── __init__.py           # Package exports
├── config.py             # Frozen configuration (v1.0) and policy definitions
├── parser.py             # SQLGlot wrapper with SQLite dialect support
├── schema_analyzer.py    # Schema catalog and table verification
├── ast_analyzer.py       # AST feature extractor (operations, tables, clauses)
├── policy_engine.py      # Deterministic policy rules (DROP, unconstrained writes, etc.)
├── firewall.py           # Main ASTSQLPolicyFirewall gateway interface
├── evaluator.py          # Benchmark evaluator and metrics computer
├── README.md             # Baseline documentation
├── tests/                # 31 unit and integration tests
│   ├── test_parser.py
│   ├── test_ast_analyzer.py
│   ├── test_policy_engine.py
│   └── test_firewall.py
└── results/              # Evaluation outputs and manifests
    ├── dev_336_results.json
    ├── heldout_342_results.json
    ├── heldout_342_summary.md
    ├── benign_50_results.json
    └── experiment_manifest.json
```

## Running Evaluations

### Automated Suite
```cmd
run_final_ast_evaluation.bat
```

### Direct CLI
```bash
# Held-out 342 mutations
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_fresh_mutations_dataset.json --output bird_eval/ast_firewall/results/heldout_342_results.json

# Benign 50 queries
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_mini_dev_50_eval.json --output bird_eval/ast_firewall/results/benign_50_results.json --type benign
```

### Unit Tests
```bash
python -m pytest bird_eval/ast_firewall/tests -v
```
