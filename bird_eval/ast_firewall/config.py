"""
AST-based SQL Policy Firewall Configuration.
Version 1.0 (Frozen).
"""

AST_FIREWALL_VERSION = "1.0"

# SQLGlot dialect
SQL_DIALECT = "sqlite"

# Policy Toggles (Fixed, deterministic, non-LLM)
POLICY_DROP_ENABLED = True
POLICY_TRUNCATE_ENABLED = True
POLICY_ALTER_ENABLED = True
POLICY_DELETE_NO_WHERE_ENABLED = True
POLICY_UPDATE_NO_WHERE_ENABLED = True
POLICY_UNKNOWN_TABLE_ENABLED = True
POLICY_UNKNOWN_COLUMN_ENABLED = False  # Disabled by default to avoid false positives on computed/unqualified columns, see Sec. 10
POLICY_PARSER_FAILURE_BLOCK = True
POLICY_MULTI_STATEMENT_BLOCK = True

# Trivial WHERE predicates that degenerate to full-table operations
TRIVIAL_PREDICATES = {
    "1 = 1",
    "1=1",
    "true",
    "1",
    "'1' = '1'",
    "'a' = 'a'",
}

# Default database directory
DEFAULT_DEV_DATABASES_DIR = "bird_eval/databases/data_minidev/MINIDEV/dev_databases"
