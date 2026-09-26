"""
Schema Analyzer module for the AST Policy Firewall.
Loads, introspects, and verifies table/column existence against database schemas.
"""

import os
import sqlite3
from typing import Dict, Set, Optional, List
from pathlib import Path

from .config import DEFAULT_DEV_DATABASES_DIR


class SchemaAnalyzer:
    """
    Introspects and caches database schemas for table and column verification.
    """

    def __init__(self, databases_dir: str = DEFAULT_DEV_DATABASES_DIR):
        self.databases_dir = Path(databases_dir)
        # Cache structure: {db_id: {table_name_lower: {col_name_lower, ...}}}
        self._schema_cache: Dict[str, Dict[str, Set[str]]] = {}

    def register_schema(self, db_id: str, schema_dict: Dict[str, List[str]]):
        """
        Manually register a schema for testing or standalone execution.
        schema_dict: {"table_name": ["col1", "col2"]}
        """
        db_key = db_id.lower()
        self._schema_cache[db_key] = {}
        for table, cols in schema_dict.items():
            self._schema_cache[db_key][table.lower()] = {c.lower() for c in cols}

    def load_db_schema(self, db_id: str) -> Optional[Dict[str, Set[str]]]:
        """
        Loads schema from SQLite database if not already cached.
        """
        db_key = db_id.lower()
        if db_key in self._schema_cache:
            return self._schema_cache[db_key]

        # Locate sqlite file
        db_path = self.databases_dir / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            # Try recursive search if direct path does not match
            matches = list(self.databases_dir.glob(f"**/{db_id}.sqlite"))
            if matches:
                db_path = matches[0]
            else:
                return None

        schema: Dict[str, Set[str]] = {}
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            # Query non-internal tables
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [row[0] for row in cur.fetchall()]
            for t in tables:
                cur.execute(f'PRAGMA table_info("{t}");')
                cols = [row[1] for row in cur.fetchall()]
                schema[t.lower()] = {c.lower() for c in cols}
            conn.close()
            self._schema_cache[db_key] = schema
            return schema
        except Exception:
            return None

    def table_exists(self, db_id: Optional[str], table_name: str) -> bool:
        """
        Checks whether a table exists in the schema for db_id.
        If no db_id or schema cannot be found, returns True (cannot definitively reject).
        """
        if not db_id or not table_name:
            return True

        schema = self.load_db_schema(db_id)
        if schema is None:
            # If schema is unavailable, do not false-positive
            return True

        return table_name.lower() in schema

    def get_tables(self, db_id: Optional[str]) -> Optional[Set[str]]:
        """
        Returns all table names for db_id (lowercase).
        """
        if not db_id:
            return None
        schema = self.load_db_schema(db_id)
        if schema is None:
            return None
        return set(schema.keys())

    def get_columns(self, db_id: Optional[str], table_name: str) -> Optional[Set[str]]:
        """
        Returns all column names for table in db_id (lowercase).
        """
        if not db_id or not table_name:
            return None
        schema = self.load_db_schema(db_id)
        if schema is None:
            return None
        return schema.get(table_name.lower())
