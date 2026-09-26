"""
Tests for ASTAnalyzer in the AST Policy Firewall.
"""

import unittest
from bird_eval.ast_firewall.parser import SQLParser
from bird_eval.ast_firewall.ast_analyzer import ASTAnalyzer


class TestASTAnalyzer(unittest.TestCase):
    def setUp(self):
        self.parser = SQLParser(dialect="sqlite")
        self.analyzer = ASTAnalyzer()

    def test_select_features(self):
        sql = "SELECT id, name FROM employees WHERE salary > 50000 ORDER BY id"
        parse_res = self.parser.parse(sql)
        features = self.analyzer.analyze(parse_res.statements)

        self.assertEqual(features.primary_operation, "SELECT")
        self.assertIn("employees", features.tables)
        self.assertIn("id", features.columns)
        self.assertIn("name", features.columns)
        self.assertIn("salary", features.columns)
        self.assertTrue(features.where_present)
        self.assertFalse(features.is_trivial_where)
        self.assertTrue(features.is_read_only)
        self.assertFalse(features.is_write)

    def test_trivial_where_predicate(self):
        sql = "DELETE FROM employees WHERE 1=1"
        parse_res = self.parser.parse(sql)
        features = self.analyzer.analyze(parse_res.statements)

        self.assertEqual(features.primary_operation, "DELETE")
        self.assertTrue(features.where_present)
        self.assertTrue(features.is_trivial_where)
        self.assertTrue(features.has_delete)
        self.assertTrue(features.is_write)

    def test_drop_operation(self):
        sql = "DROP TABLE users"
        parse_res = self.parser.parse(sql)
        features = self.analyzer.analyze(parse_res.statements)

        self.assertEqual(features.primary_operation, "DROP")
        self.assertTrue(features.has_drop)
        self.assertTrue(features.is_write)
        self.assertIn("users", features.tables)

    def test_alter_operation(self):
        sql = "ALTER TABLE users ADD COLUMN age INT"
        parse_res = self.parser.parse(sql)
        features = self.analyzer.analyze(parse_res.statements)

        self.assertEqual(features.primary_operation, "ALTER")
        self.assertTrue(features.has_alter)
        self.assertTrue(features.is_write)

    def test_truncate_operation(self):
        sql = "TRUNCATE TABLE users"
        parse_res = self.parser.parse(sql)
        features = self.analyzer.analyze(parse_res.statements)

        self.assertTrue(features.has_truncate)
        self.assertTrue(features.is_write)

    def test_cte_exclusion_from_physical_tables(self):
        sql = "WITH cte_summary AS (SELECT id FROM raw_data) SELECT * FROM cte_summary JOIN customers ON cte_summary.id = customers.id"
        parse_res = self.parser.parse(sql)
        features = self.analyzer.analyze(parse_res.statements)

        self.assertIn("cte_summary", features.cte_names)
        self.assertNotIn("cte_summary", features.tables)
        self.assertIn("raw_data", features.tables)
        self.assertIn("customers", features.tables)


if __name__ == "__main__":
    unittest.main()
