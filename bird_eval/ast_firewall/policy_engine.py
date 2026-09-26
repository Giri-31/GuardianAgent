"""
Policy Engine module for the AST Policy Firewall.
Evaluates deterministic security policies against extracted AST features and schema context.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import sqlglot
from sqlglot import exp

from .config import (
    POLICY_DROP_ENABLED,
    POLICY_TRUNCATE_ENABLED,
    POLICY_ALTER_ENABLED,
    POLICY_DELETE_NO_WHERE_ENABLED,
    POLICY_UPDATE_NO_WHERE_ENABLED,
    POLICY_UNKNOWN_TABLE_ENABLED,
    TRIVIAL_PREDICATES,
)
from .ast_analyzer import ASTFeatures
from .schema_analyzer import SchemaAnalyzer


@dataclass
class PolicyEvaluationResult:
    """
    Result of evaluating all policies against an AST.
    """
    decision: str  # "SAFE" or "UNSAFE"
    violations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """
    Deterministic rule-based policy engine for AST SQL firewall.
    """

    def __init__(
        self,
        block_drop: bool = POLICY_DROP_ENABLED,
        block_truncate: bool = POLICY_TRUNCATE_ENABLED,
        block_alter: bool = POLICY_ALTER_ENABLED,
        block_delete_no_where: bool = POLICY_DELETE_NO_WHERE_ENABLED,
        block_update_no_where: bool = POLICY_UPDATE_NO_WHERE_ENABLED,
        block_unknown_table: bool = POLICY_UNKNOWN_TABLE_ENABLED,
    ):
        self.block_drop = block_drop
        self.block_truncate = block_truncate
        self.block_alter = block_alter
        self.block_delete_no_where = block_delete_no_where
        self.block_update_no_where = block_update_no_where
        self.block_unknown_table = block_unknown_table

    def _is_trivial_where(self, where_node: Optional[exp.Where]) -> bool:
        if where_node is None or where_node.this is None:
            return True
        where_sql = where_node.this.sql().strip().lower().replace(" ", "")
        for trivial in TRIVIAL_PREDICATES:
            if where_sql == trivial.replace(" ", ""):
                return True
        return False

    def evaluate(
        self,
        features: ASTFeatures,
        statements: List[exp.Expression],
        schema_analyzer: Optional[SchemaAnalyzer] = None,
        db_id: Optional[str] = None,
    ) -> PolicyEvaluationResult:
        violations: List[str] = []
        details: Dict[str, Any] = {
            "operations": features.operations,
            "primary_operation": features.primary_operation,
            "tables": features.tables,
            "statement_count": len(statements),
            "where_present": features.where_present,
        }

        # Statement-by-statement inspection
        for idx, stmt in enumerate(statements):
            # POLICY 1: DROP
            if self.block_drop:
                if isinstance(stmt, exp.Drop) or stmt.find(exp.Drop) is not None:
                    violations.append("DROP_DETECTED")
                elif stmt.sql().lower().startswith("drop "):
                    violations.append("DROP_DETECTED")

            # POLICY 2: TRUNCATE
            if self.block_truncate:
                if isinstance(stmt, exp.TruncateTable) or "truncate" in stmt.sql().lower():
                    violations.append("TRUNCATE_DETECTED")

            # POLICY 3: ALTER
            if self.block_alter:
                if isinstance(stmt, exp.Alter) or stmt.find(exp.Alter) is not None:
                    violations.append("ALTER_DETECTED")
                elif stmt.sql().lower().startswith("alter "):
                    violations.append("ALTER_DETECTED")

            # POLICY 4: DELETE WITHOUT WHERE
            if self.block_delete_no_where:
                # Find all delete nodes in statement
                delete_nodes = [stmt] if isinstance(stmt, exp.Delete) else list(stmt.find_all(exp.Delete))
                for del_node in delete_nodes:
                    where_node = del_node.find(exp.Where)
                    if where_node is None or self._is_trivial_where(where_node):
                        violations.append("DELETE_WITHOUT_WHERE")

            # POLICY 5: UPDATE WITHOUT WHERE
            if self.block_update_no_where:
                # Find all update nodes in statement
                update_nodes = [stmt] if isinstance(stmt, exp.Update) else list(stmt.find_all(exp.Update))
                for upd_node in update_nodes:
                    where_node = upd_node.find(exp.Where)
                    if where_node is None or self._is_trivial_where(where_node):
                        violations.append("UPDATE_WITHOUT_WHERE")

        # POLICY 6: TABLE ACCESS POLICY (Schema validation)
        if self.block_unknown_table and schema_analyzer is not None and db_id is not None:
            unknown_tables = []
            for table_name in features.tables:
                if not schema_analyzer.table_exists(db_id, table_name):
                    unknown_tables.append(table_name)
            if unknown_tables:
                violations.append(f"UNKNOWN_TABLES: {', '.join(unknown_tables)}")
                details["unknown_tables"] = unknown_tables

        # Deduplicate violations while preserving order
        unique_violations = list(dict.fromkeys(violations))
        decision = "UNSAFE" if len(unique_violations) > 0 else "SAFE"

        details["violations"] = unique_violations
        return PolicyEvaluationResult(
            decision=decision,
            violations=unique_violations,
            details=details,
        )
