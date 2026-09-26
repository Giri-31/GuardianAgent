@echo off
REM =========================================================================
REM GuardianAgent Research Suite: AST SQL Policy Firewall Reproduction Script
REM =========================================================================

echo [1/4] Running AST Firewall Unit Tests (31 tests)...
python -m pytest bird_eval/ast_firewall/tests -v
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Unit tests failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [2/4] Running Development Evaluation (336 cases)...
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_mutations_dataset.json --output bird_eval/ast_firewall/results/dev_336_results.json
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Development evaluation failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [3/4] Running Held-Out Evaluation (342 cases)...
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_fresh_mutations_dataset.json --output bird_eval/ast_firewall/results/heldout_342_results.json
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Held-out evaluation failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [4/4] Running Benign Evaluation (50 clean gold queries)...
python run_ast_firewall_eval.py --dataset bird_eval/results/bird_mini_dev_50_eval.json --output bird_eval/ast_firewall/results/benign_50_results.json --type benign
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Benign evaluation failed!
    exit /b %ERRORLEVEL%
)

echo.
echo =========================================================================
echo All AST SQL Policy Firewall evaluations completed successfully.
echo Output files:
echo   - bird_eval/ast_firewall/results/dev_336_results.json
echo   - bird_eval/ast_firewall/results/heldout_342_results.json
echo   - bird_eval/ast_firewall/results/benign_50_results.json
echo   - bird_eval/ast_firewall/results/heldout_342_summary.md
echo   - AST_FIREWALL_FINAL_REPORT.md
echo =========================================================================
