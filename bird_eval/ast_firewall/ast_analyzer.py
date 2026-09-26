"""
AST Analyzer module for the AST Policy Firewall.
Inspects SQLGlot AST expressions and extracts structural security features.
"""

from dataclasses import dataclass, field
from typing import List, Set, Optional
import sqlglot
from sqlglot import exp

from .config import TRIVIAL_PREDICATES


@dataclass
class ASTFeatures:
    """
    Extracted structural and semantic properties from SQL AST.
    """
    statement_count: int = 1
    operations: List[str] = field(default_factory=list)
    primary_operation: str = "UNKNOWN"
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    where_present: bool = False
    where_clause_sql: Optional[str] = None
    is_trivial_where: bool = False
    has_drop: bool = False
    has_truncate: bool = False
    has_alter: bool = False
    has_delete: bool = False
    has_update: bool = False
    has_create: bool = False
    is_write: bool = False
    is_read_only: bool = True
    cte_names: List[str] = field(default_factory=list)


class ASTAnalyzer:
    """
    Analyzes AST expressions to extract safety-relevant structural features.
    """

    def analyze_expression(self, expression: exp.Expression) -> ASTFeatures:
        """
        Analyzes a single SQLGlot Expression node.
        """
        features = ASTFeatures()
        features.statement_count = 1

        # 1. Operation classification
        op_name = type(expression).__name__.upper()
        if isinstance(expression, exp.Select):
            features.operations.append("SELECT")
            features.primary_operation = "SELECT"
            features.is_read_only = True
        elif isinstance(expression, exp.Insert):
            features.operations.append("INSERT")
            features.primary_operation = "INSERT"
            features.is_write = True
            features.is_read_only = False
        elif isinstance(expression, exp.Update):
            features.operations.append("UPDATE")
            features.primary_operation = "UPDATE"
            features.has_update = True
            features.is_write = True
            features.is_read_only = False
        elif isinstance(expression, exp.Delete):
            features.operations.append("DELETE")
            features.primary_operation = "DELETE"
            features.has_delete = True
            features.is_write = True
            features.is_read_only = False
        elif isinstance(expression, exp.Drop):
            features.operations.append("DROP")
            features.primary_operation = "DROP"
            features.has_drop = True
            features.is_write = True
            features.is_read_only = False
        elif isinstance(expression, exp.Alter):
            features.operations.append("ALTER")
            features.primary_operation = "ALTER"
            features.has_alter = True
            features.is_write = True
            features.is_read_only = False
        elif isinstance(expression, (exp.TruncateTable, exp.Command)) and "truncate" in expression.sql().lower():
            features.operations.append("TRUNCATE")
            features.primary_operation = "TRUNCATE"
            features.has_truncate = True
            features.is_write = True
            features.is_read_only = False
        elif isinstance(expression, exp.Create):
            features.operations.append("CREATE")
            features.primary_operation = "CREATE"
            features.has_create = True
            features.is_write = True
            features.is_read_only = False
        else:
            # Fallback based on SQL string inspection if expression node is generic
            sql_lower = expression.sql().lower()
            if sql_lower.startswith("drop"):
                features.operations.append("DROP")
                features.primary_operation = "DROP"
                features.has_drop = True
                features.is_write = True
                features.is_read_only = False
            elif sql_lower.startswith("truncate"):
                features.operations.append("TRUNCATE")
                features.primary_operation = "TRUNCATE"
                features.has_truncate = True
                features.is_write = True
                features.is_read_only = False
            elif sql_lower.startswith("alter"):
                features.operations.append("ALTER")
                features.primary_operation = "ALTER"
                features.has_alter = True
                features.is_write = True
                features.is_read_only = False
            else:
                features.operations.append(op_name)
                features.primary_operation = op_name

        # Also search for embedded destructive statements in any sub-expression
        for drop_node in expression.find_all(exp.Drop):
            features.has_drop = True
            features.is_write = True
            features.is_read_only = False
        for alter_node in expression.find_all(exp.Alter):
            features.has_alter = True
            features.is_write = True
            features.is_read_only = False
        for trunc_node in expression.find_all(exp.TruncateTable):
            features.has_truncate = True
            features.is_write = True
            features.is_read_only = False

        # 2. Extract CTEs so they are not treated as physical schema tables
        ctes: Set[str] = set()
        for cte in expression.find_all(exp.CTE):
            if cte.alias:
                ctes.add(cte.alias.lower())
        features.cte_names = sorted(list(ctes))

        # 3. Extract Tables
        tables: Set[str] = set()
        for table_node in expression.find_all(exp.Table):
            t_name = table_node.name
            if t_name and t_name.lower() not in ctes:
                tables.add(t_name.lower())
        features.tables = sorted(list(tables))

        # 4. Extract Columns
        cols: Set[str] = set()
        for col_node in expression.find_all(exp.Column):
            c_name = col_node.name
            if c_name and c_name != "*":
                cols.add(c_name.lower())
        features.columns = sorted(list(cols))

        # 5. Extract WHERE clause and Scope
        # Look for WHERE clause in top statement or relevant DML
        where_node = expression.find(exp.Where)
        if where_node is not None:
            features.where_present = True
            where_sql = where_node.this.sql().strip() if where_node.this else ""
            features.where_clause_sql = where_sql
            # Check for trivial WHERE condition (e.g. WHERE 1=1 or WHERE TRUE)
            clean_where = where_sql.lower().replace(" ", "")
            for trivial in TRIVIAL_PREDICATES:
                if clean_where == trivial.replace(" ", ""):
                    features.is_trivial_where = True
                    break
        else:
            features.where_present = False
            features.where_clause_sql = None
            features.is_trivial_where = False

        return features

    def analyze(self, statements: List[exp.Expression]) -> ASTFeatures:
        """
        Analyzes a list of statements (such as a multi-statement script).
        Aggregates features across all statements.
        """
        if not statements:
            return ASTFeatures(statement_count=0)

        if len(statements) == 1:
            return self.analyze_expression(statements[0])

        # Multiple statements
        combined = ASTFeatures()
        combined.statement_count = len(statements)
        combined.is_read_only = True
        tables_set = set()
        cols_set = set()
        cte_set = set()

        for stmt in statements:
            sub = self.analyze_expression(stmt)
            combined.operations.extend(sub.operations)
            if sub.has_drop:
                combined.has_drop = True
            if sub.has_truncate:
                combined.has_truncate = True
            if sub.has_alter:
                combined.has_alter = True
            if sub.has_delete:
                combined.has_delete = True
            if sub.has_update:
                combined.has_update = True
            if sub.has_create:
                combined.has_create = True
            if sub.is_write:
                combined.is_write = True
                combined.is_read_only = False
            if sub.where_present:
                combined.where_present = True
            if sub.is_trivial_where:
                combined.is_trivial_where = True

            tables_set.update(sub.tables)
            cols_set.update(sub.columns)
            cte_set.update(sub.cte_names)

        combined.tables = sorted(list(tables_set))
        combined.columns = sorted(list(cols_set))
        combined.cte_names = sorted(list(cte_set))
        combined.primary_operation = combined.operations[0] if combined.operations else "UNKNOWN"
        return combined
