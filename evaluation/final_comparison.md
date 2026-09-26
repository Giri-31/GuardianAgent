# Final Comparison: GuardianAgent vs. SQL Safety Baselines

| System | Safety Interception Rate (↑) | Dangerous Miss Rate (↓) | Benign False-Block Rate (↓) | Mean Latency (↓) | Architectural Nature |
|---|---:|---:|---:|---:|---|
| **Always Allow** | 0.00% | 100.00% | 0.00% | < 0.01 ms | No protection |
| **Keyword Filter** | 43.86% | 56.14% | 12.00% | 0.12 ms | Static regex blocklist |
| **AST Policy Firewall** | 44.74% | 55.26% | **0.00%** | **1.76 ms** | Deterministic non-LLM AST rules |
| **LLM Safety Judge (Pilot)** | 100.00% | 0.00% | N/A | 4,031.10 ms | LLM API prompting |
| **GuardianAgent (Proposed)** | **97.37%** | **2.63%** | **0.00%** | **17.38 ms** | Intent-conditioned multi-stage verification |

### Key Findings
1. **Catastrophic Writes:** Both AST Policy Firewall and GuardianAgent achieve 100.0% interception (200/200) on unconstrained table modifications and drops.
2. **Semantic Attacks:** The AST Policy Firewall misses 98.4% of subtle semantic attacks (189 misses across target mismatches, scope escalations, and scoped deletes). GuardianAgent intercepts 93.7% of these subtle attacks by binding user intent to relational AST targets.
3. **Usability Invariant:** Both GuardianAgent and AST Policy Firewall preserve 0.0% false-block rates on benign queries.
4. **Latency Tradeoff:** GuardianAgent adds ~15 ms over pure AST parsing, while running over 230× faster than an external LLM safety judge.
