"""
Main Firewall interface for the AST SQL Policy Firewall.
Orchestrates parsing, schema loading, AST analysis, policy evaluation, and latency measurement.
"""

import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from .config import AST_FIREWALL_VERSION, SQL_DIALECT, POLICY_PARSER_FAILURE_BLOCK
from .parser import SQLParser, ParseResult
from .schema_analyzer import SchemaAnalyzer
from .ast_analyzer import ASTAnalyzer, ASTFeatures
from .policy_engine import PolicyEngine, PolicyEvaluationResult


@dataclass
class FirewallResult:
    decision: str  # "SAFE" or "UNSAFE"
    violations: List[str] = field(default_factory=list)
    operation: str = "UNKNOWN"
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    where_present: bool = False
    is_parser_failure: bool = False
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    raw_sql: str = ""
    db_id: Optional[str] = None
    ast_version: str = AST_FIREWALL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ASTSQLPolicyFirewall:
    """
    Standalone, deterministic, non-LLM AST-based SQL Policy Firewall.
    """

    def __init__(
        self,
        dialect: str = SQL_DIALECT,
        databases_dir: Optional[str] = None,
        parser: Optional[SQLParser] = None,
        schema_analyzer: Optional[SchemaAnalyzer] = None,
        ast_analyzer: Optional[ASTAnalyzer] = None,
        policy_engine: Optional[PolicyEngine] = None,
    ):
        self.version = AST_FIREWALL_VERSION
        self.parser = parser or SQLParser(dialect=dialect)
        if schema_analyzer:
            self.schema_analyzer = schema_analyzer
        elif databases_dir:
            self.schema_analyzer = SchemaAnalyzer(databases_dir=databases_dir)
        else:
            self.schema_analyzer = SchemaAnalyzer()

        self.ast_analyzer = ast_analyzer or ASTAnalyzer()
        self.policy_engine = policy_engine or PolicyEngine()

    def check_query(self, sql: str, db_id: Optional[str] = None) -> FirewallResult:
        """
        Main inspection entry point.
        Analyzes SQL syntax, structural AST, schema references, and applies deterministic safety policies.
        """
        start_time = time.perf_counter()

        # Step 1: Parse SQL
        parse_result: ParseResult = self.parser.parse(sql)
        if not parse_result.is_success:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            violations = ["PARSER_FAILURE"] if POLICY_PARSER_FAILURE_BLOCK else []
            decision = "UNSAFE" if POLICY_PARSER_FAILURE_BLOCK else "SAFE"
            return FirewallResult(
                decision=decision,
                violations=violations,
                operation="UNKNOWN",
                tables=[],
                columns=[],
                where_present=False,
                is_parser_failure=True,
                error_message=parse_result.error_message,
                latency_ms=round(latency_ms, 4),
                raw_sql=sql,
                db_id=db_id,
                ast_version=self.version,
            )

        # Step 2: AST Analysis
        features: ASTFeatures = self.ast_analyzer.analyze(parse_result.statements)

        # Step 3: Policy Evaluation
        eval_result: PolicyEvaluationResult = self.policy_engine.evaluate(
            features=features,
            statements=parse_result.statements,
            schema_analyzer=self.schema_analyzer,
            db_id=db_id,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return FirewallResult(
            decision=eval_result.decision,
            violations=eval_result.violations,
            operation=features.primary_operation,
            tables=features.tables,
            columns=features.columns,
            where_present=features.where_present,
            is_parser_failure=False,
            error_message=None,
            latency_ms=round(latency_ms, 4),
            raw_sql=sql,
            db_id=db_id,
            ast_version=self.version,
        )
