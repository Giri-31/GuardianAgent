"""
Tests for PolicyEngine in the AST Policy Firewall.
"""

import unittest
from bird_eval.ast_firewall.parser import SQLParser
from bird_eval.ast_firewall.ast_analyzer import ASTAnalyzer
from bird_eval.ast_firewall.schema_analyzer import SchemaAnalyzer
from bird_eval.ast_firewall.policy_engine import PolicyEngine


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.parser = SQLParser(dialect="sqlite")
        self.analyzer = ASTAnalyzer()
        self.schema = SchemaAnalyzer()
        self.schema.register_schema("test_db", {
            "employees": ["id", "name", "salary"],
            "departments": ["dept_id", "dept_name"]
        })
        self.policy = PolicyEngine()

    def _eval(self, sql, db_id="test_db"):
        parsed = self.parser.parse(sql)
        self.assertTrue(parsed.is_success, f"Failed parsing: {sql}")
        features = self.analyzer.analyze(parsed.statements)
        return self.policy.evaluate(
            features=features,
            statements=parsed.statements,
            schema_analyzer=self.schema,
            db_id=db_id,
        )

    def test_safe_select(self):
        res = self._eval("SELECT name FROM employees WHERE id = 1;")
        self.assertEqual(res.decision, "SAFE")
        self.assertEqual(len(res.violations), 0)

    def test_policy_drop(self):
        res = self._eval("DROP TABLE employees;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("DROP_DETECTED", res.violations)

    def test_policy_truncate(self):
        res = self._eval("TRUNCATE TABLE employees;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("TRUNCATE_DETECTED", res.violations)

    def test_policy_alter(self):
        res = self._eval("ALTER TABLE employees ADD COLUMN active INT;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("ALTER_DETECTED", res.violations)

    def test_policy_delete_without_where(self):
        res = self._eval("DELETE FROM employees;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("DELETE_WITHOUT_WHERE", res.violations)

    def test_policy_delete_with_where(self):
        res = self._eval("DELETE FROM employees WHERE id = 5;")
        self.assertEqual(res.decision, "SAFE")
        self.assertEqual(len(res.violations), 0)

    def test_policy_delete_with_trivial_where(self):
        res = self._eval("DELETE FROM employees WHERE 1 = 1;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("DELETE_WITHOUT_WHERE", res.violations)

    def test_policy_update_without_where(self):
        res = self._eval("UPDATE employees SET salary = salary * 1.1;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("UPDATE_WITHOUT_WHERE", res.violations)

    def test_policy_update_with_where(self):
        res = self._eval("UPDATE employees SET salary = salary * 1.1 WHERE id = 5;")
        self.assertEqual(res.decision, "SAFE")
        self.assertEqual(len(res.violations), 0)

    def test_policy_unknown_table(self):
        res = self._eval("SELECT * FROM nonexistent_table;")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertTrue(any("UNKNOWN_TABLE" in v for v in res.violations))


if __name__ == "__main__":
    unittest.main()
