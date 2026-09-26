"""
Generate paper-ready CSV tables for GuardianAgent IEEE evaluation.
"""

import csv
from pathlib import Path

def generate_tables():
    tables_dir = Path("evaluation/tables")
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Table 1: Main Results
    table1_rows = [
        ["Method", "Approach", "Cases", "Strict BLOCK Accuracy (%)", "Safety Interception (%)", "Dangerous Miss Rate (%)", "Benign False-Block (%)", "Mean Latency (ms)"],
        ["Always Allow", "No protection", "342", "0.00%", "0.00%", "100.00%", "0.00%", "< 0.01"],
        ["Keyword Filter", "Rule-based regex", "342", "43.86%", "43.86%", "56.14%", "12.00%", "0.12"],
        ["AST Policy Firewall", "Non-LLM AST + policies", "342", "44.74%", "44.74%", "55.26%", "0.00%", "1.76"],
        ["LLM Safety Judge (Pilot)", "LLM-as-a-judge (Gemini)", "8", "100.00%", "100.00%", "0.00%", "N/A", "4031.10"],
        ["GuardianAgent (Proposed)", "Multi-stage intent gateway", "342", "91.81%", "97.37%", "2.63%", "0.00%", "17.38"],
    ]
    with open(tables_dir / "table1_main_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(table1_rows)

    # Table 2: Category Results
    table2_rows = [
        ["Category", "Cases", "Strict Correct", "Strict Accuracy (%)", "Intercepted", "Escapes", "Interception Rate (%)"],
        ["DANGEROUS_DELETE", "50", "50", "100.00%", "50", "0", "100.00%"],
        ["DANGEROUS_DELETE_WHERE", "50", "50", "100.00%", "50", "0", "100.00%"],
        ["DANGEROUS_DROP", "50", "50", "100.00%", "50", "0", "100.00%"],
        ["DANGEROUS_UPDATE", "50", "50", "100.00%", "50", "0", "100.00%"],
        ["FIELD_INJECT", "45", "44", "97.78%", "45", "0", "100.00%"],
        ["SCOPE_ESCALATION", "47", "40", "85.11%", "40", "7", "85.11%"],
        ["TARGET_MISMATCH", "50", "30", "60.00%", "49", "1", "98.00%"],
        ["Total", "342", "314", "91.81%", "333", "9", "97.37%"],
    ]
    with open(tables_dir / "table2_category_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(table2_rows)

    # Table 3: Ablation
    table3_rows = [
        ["Component Variant", "Total Cases", "Overall Safety Interception (%)", "Semantic-Attack Interception (142 cases) (%)"],
        ["Dumb Keyword Blocklist", "342", "150 / 342 (43.86%)", "0 / 142 (0.00%)"],
        ["Pure Consequence Scoring (No Overrides)*", "342", "342 / 342 (100.00%)*", "142 / 142 (100.00%)*"],
        ["Full GuardianAgent Pipeline", "342", "333 / 342 (97.37%)", "133 / 142 (93.66%)"],
    ]
    with open(tables_dir / "table3_ablation.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(table3_rows)

    # Table 4: Benign Usability
    table4_rows = [
        ["Evaluation Regime", "Cases", "ALLOW (Count, %)", "CONFIRM (Count, %)", "BLOCK (Count, %)", "False-Block Rate (%)", "Interruption Rate (%)", "Mean Latency (ms)"],
        ["Pre-Calibration Baseline", "50", "17 (34.00%)", "9 (18.00%)", "24 (48.00%)", "48.00%", "66.00%", "0.33"],
        ["Post-Calibration Final", "50", "31 (62.00%)", "19 (38.00%)", "0 (0.00%)", "0.00%", "38.00%", "17.38"],
    ]
    with open(tables_dir / "table4_benign.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(table4_rows)

    # Table 5: DBBench End-to-End
    table5_rows = [
        ["Dimension", "Metric", "Value"],
        ["Agent Task Success", "Total Tasks Evaluated", "60"],
        ["Agent Task Success", "Correct Completed Tasks", "46"],
        ["Agent Task Success", "Task Success Rate (%)", "76.67%"],
        ["Database Safety", "Safety Invariant Violations", "0"],
        ["Database Safety", "Dangerous SQL Escapes", "0"],
        ["Gateway Actions", "Autonomous ALLOW", "8 (13.33%)"],
        ["Gateway Actions", "Human Review (CONFIRM)", "8 (13.33%)"],
        ["Gateway Actions", "Autonomous Interception (BLOCK)", "44 (73.33%)"],
        ["Gateway Actions", "Human Intervention Rate (%)", "13.33%"],
        ["Performance", "Mean Latency (ms)", "2.49"],
        ["Performance", "Median Latency (ms)", "1.82"],
    ]
    with open(tables_dir / "table5_dbbench.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(table5_rows)

    print("All 5 CSV tables created successfully in evaluation/tables/.")

if __name__ == "__main__":
    generate_tables()
