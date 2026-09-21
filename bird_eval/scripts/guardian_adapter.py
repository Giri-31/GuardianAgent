"""
guardian_adapter.py

Adapter isolating BIRD evaluation pipeline from GuardianAgent core code.
Exposes clean interfaces to:
1. Connect safely to BIRD SQLite databases.
2. Invoke the frozen GuardianAgent safety verification pipeline.
3. Normalize and extract GuardianAgent risk metrics, decisions, and intent-SQL checks.
"""

import os
import sqlite3
import sys
import time
from pathlib import Path

# Add repository root to path
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guardian import guardian_check  # noqa: E402
from sql_analyzer import analyze_sql  # noqa: E402


class GuardianBIRDAdapter:
    """
    Adapter between BIRD database evaluation tasks and GuardianAgent safety layer.
    """

    def __init__(self, disable_llm_intent: bool = False):
        """
        Initialize the adapter.
        :param disable_llm_intent: If True, sets GUARDIAN_DISABLE_LLM=1 to use deterministic
                                   intent analysis instead of calling Gemini API.
        """
        self.disable_llm_intent = disable_llm_intent
        if disable_llm_intent:
            os.environ["GUARDIAN_DISABLE_LLM"] = "1"

    def open_database_connection(self, db_path: Path, read_only: bool = True) -> sqlite3.Connection:
        """
        Open a connection to a BIRD SQLite database.
        Optionally uses read-only URI mode to prevent any accidental mutations to the official database.
        """
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found at: {db_path}")

        if read_only:
            # Open with URI read-only flag
            uri_path = f"file:{db_path.resolve().as_posix()}?mode=ro"
            return sqlite3.connect(uri_path, uri=True)
        else:
            return sqlite3.connect(str(db_path))

    def evaluate_query(
        self,
        user_request: str,
        sql: str,
        connection: sqlite3.Connection = None,
        table_name: str = None,
        known_intent: dict = None,
    ) -> dict:
        """
        Passes a natural language request and SQL into GuardianAgent for safety verification.

        Returns a normalized dictionary containing:
        - decision: ALLOW, CONFIRM, BLOCK
        - risk_score: float (0.0 to 10.0)
        - risk_level: LOW, MEDIUM, HIGH, CRITICAL
        - scope: ZERO_ROWS, ONE_ROW, MULTIPLE_ROWS, ALL_ROWS, UNKNOWN
        - impact_type: READ, DATA_CREATION, DATA_MUTATION, DATA_DELETION, etc.
        - mismatches: list of detected inconsistencies (e.g. FIELD_MISMATCH, SCOPE_MISMATCH)
        - intent: canonical extracted intent dict
        - latency_ms: float
        """
        start_time = time.perf_counter()
        
        # If table_name is not provided, attempt to infer primary table from SQL
        if not table_name and sql:
            sql_info = analyze_sql(sql)
            table_name = sql_info.get("table")

        try:
            res = guardian_check(
                user_request=user_request,
                sql=sql,
                known_intent=known_intent,
                connection=connection,
                table_name=table_name or "unknown",
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            risk = res.get("risk", {})
            intent_sql = res.get("intent_sql", {})

            return {
                "decision": risk.get("decision", "BLOCK"),
                "risk_score": risk.get("risk_score", 10.0),
                "risk_level": risk.get("risk_level", "HIGH"),
                "scope": res.get("scope", "UNKNOWN"),
                "impact": res.get("impact", {}),
                "mismatches": intent_sql.get("mismatches", []),
                "intent": res.get("intent", {}),
                "sql_info": res.get("sql_info", {}),
                "latency_ms": round(elapsed_ms, 3),
                "error": None,
            }
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return {
                "decision": "BLOCK",
                "risk_score": 10.0,
                "risk_level": "CRITICAL",
                "scope": "UNKNOWN",
                "impact": {"impact_type": "UNKNOWN", "risk_level": "CRITICAL"},
                "mismatches": ["EVALUATION_EXCEPTION"],
                "intent": {},
                "sql_info": {},
                "latency_ms": round(elapsed_ms, 3),
                "error": str(e),
            }
