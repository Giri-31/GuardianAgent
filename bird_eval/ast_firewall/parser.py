"""
SQL Parser module using SQLGlot for the AST Policy Firewall.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import sqlglot
from sqlglot import exp, errors

from .config import SQL_DIALECT


@dataclass
class ParseResult:
    is_success: bool
    statements: List[exp.Expression] = field(default_factory=list)
    error_message: Optional[str] = None
    raw_sql: str = ""
    dialect_used: str = SQL_DIALECT


class SQLParser:
    """
    Deterministic SQL parser wrapping SQLGlot.
    """

    def __init__(self, dialect: str = SQL_DIALECT):
        self.dialect = dialect

    def clean_sql(self, sql: Optional[str]) -> str:
        """
        Normalize SQL text without changing its meaning.
        Removes markdown code fences and whitespace.
        """
        if sql is None:
            return ""
        s = sql.strip()
        if s.startswith("```"):
            lines = s.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        # Remove trailing semicolons for single queries if needed, but sqlglot handles semicolons
        return s

    def parse(self, sql: str) -> ParseResult:
        """
        Parses SQL text into a list of SQLGlot expression ASTs.
        """
        cleaned = self.clean_sql(sql)
        if not cleaned:
            return ParseResult(
                is_success=False,
                error_message="Empty SQL string",
                raw_sql=sql,
                dialect_used=self.dialect,
            )

        try:
            # First attempt with specified dialect
            stmts = sqlglot.parse(cleaned, read=self.dialect)
            # Filter out None statements if any
            valid_stmts = [s for s in stmts if s is not None]
            if not valid_stmts:
                return ParseResult(
                    is_success=False,
                    error_message="No valid statements parsed",
                    raw_sql=cleaned,
                    dialect_used=self.dialect,
                )
            return ParseResult(
                is_success=True,
                statements=valid_stmts,
                raw_sql=cleaned,
                dialect_used=self.dialect,
            )
        except errors.ParseError as pe:
            # Fallback attempt with generic/default dialect before failing
            try:
                stmts = sqlglot.parse(cleaned)
                valid_stmts = [s for s in stmts if s is not None]
                if valid_stmts:
                    return ParseResult(
                        is_success=True,
                        statements=valid_stmts,
                        raw_sql=cleaned,
                        dialect_used="generic",
                    )
            except Exception:
                pass
            return ParseResult(
                is_success=False,
                error_message=f"ParseError: {str(pe)}",
                raw_sql=cleaned,
                dialect_used=self.dialect,
            )
        except Exception as ex:
            return ParseResult(
                is_success=False,
                error_message=f"Exception: {str(ex)}",
                raw_sql=cleaned,
                dialect_used=self.dialect,
            )
