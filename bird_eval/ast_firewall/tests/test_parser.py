"""
Tests for SQLParser in the AST Policy Firewall.
"""

import unittest
from bird_eval.ast_firewall.parser import SQLParser


class TestSQLParser(unittest.TestCase):
    def setUp(self):
        self.parser = SQLParser(dialect="sqlite")

    def test_clean_sql_with_markdown_fences(self):
        sql = "```sql\nSELECT * FROM test;\n```"
        cleaned = self.parser.clean_sql(sql)
        self.assertEqual(cleaned, "SELECT * FROM test;")

    def test_clean_sql_empty(self):
        self.assertEqual(self.parser.clean_sql(""), "")
        self.assertEqual(self.parser.clean_sql(None), "")

    def test_parse_valid_select(self):
        sql = "SELECT id, name FROM users WHERE id = 1"
        res = self.parser.parse(sql)
        self.assertTrue(res.is_success)
        self.assertEqual(len(res.statements), 1)

    def test_parse_multi_statements(self):
        sql = "SELECT 1; DROP TABLE test;"
        res = self.parser.parse(sql)
        self.assertTrue(res.is_success)
        self.assertEqual(len(res.statements), 2)

    def test_parse_syntax_error(self):
        sql = "SELEC * FORM users WHE id ="
        res = self.parser.parse(sql)
        self.assertFalse(res.is_success)
        self.assertIsNotNone(res.error_message)

    def test_parse_empty_string(self):
        res = self.parser.parse("   ")
        self.assertFalse(res.is_success)


if __name__ == "__main__":
    unittest.main()
