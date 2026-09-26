"""
Integration tests for the ASTSQLPolicyFirewall.
"""

import unittest
from bird_eval.ast_firewall.firewall import ASTSQLPolicyFirewall
from bird_eval.ast_firewall.schema_analyzer import SchemaAnalyzer


class TestASTSQLPolicyFirewall(unittest.TestCase):
    def setUp(self):
        self.schema = SchemaAnalyzer()
        self.schema.register_schema("company", {
            "employees": ["id", "name", "salary", "department_id"],
            "departments": ["department_id", "dept_name"]
        })
        self.firewall = ASTSQLPolicyFirewall(schema_analyzer=self.schema)

    def test_section_14_safe_select(self):
        sql = "SELECT name FROM employees WHERE id = 1;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "SAFE")
        self.assertEqual(res.operation, "SELECT")
        self.assertTrue(res.where_present)
        self.assertGreater(res.latency_ms, 0.0)

    def test_section_14_drop(self):
        sql = "DROP TABLE employees;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("DROP_DETECTED", res.violations)

    def test_section_14_delete_without_where(self):
        sql = "DELETE FROM employees;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("DELETE_WITHOUT_WHERE", res.violations)

    def test_section_14_delete_with_where(self):
        sql = "DELETE FROM employees WHERE id = 5;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "SAFE")

    def test_section_14_update_without_where(self):
        sql = "UPDATE employees SET salary = salary * 1.1;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertIn("UPDATE_WITHOUT_WHERE", res.violations)

    def test_section_14_update_with_where(self):
        sql = "UPDATE employees SET salary = salary * 1.1 WHERE id = 5;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "SAFE")

    def test_section_14_invalid_table(self):
        sql = "SELECT * FROM nonexistent_table;"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertTrue(any("UNKNOWN_TABLE" in v for v in res.violations))

    def test_complex_valid_query_joins_aggregations(self):
        sql = """
        SELECT d.dept_name, AVG(e.salary) AS avg_sal
        FROM departments AS d
        JOIN employees AS e ON d.department_id = e.department_id
        WHERE e.salary > 30000
        GROUP BY d.dept_name
        HAVING COUNT(e.id) > 2
        ORDER BY avg_sal DESC
        """
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "SAFE")
        self.assertEqual(len(res.violations), 0)

    def test_parser_failure_safety(self):
        sql = "SELECTTTT FROM WHERE id = = 123"
        res = self.firewall.check_query(sql, db_id="company")
        self.assertEqual(res.decision, "UNSAFE")
        self.assertTrue(res.is_parser_failure)
        self.assertIn("PARSER_FAILURE", res.violations)


if __name__ == "__main__":
    unittest.main()
