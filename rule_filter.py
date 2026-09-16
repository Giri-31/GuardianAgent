import re


def rule_filter(sql):
    sql_upper = sql.upper().strip()

    if "DROP TABLE" in sql_upper:
        return "BLOCK"

    if "DELETE FROM" in sql_upper and "WHERE" not in sql_upper:
        return "BLOCK"

    if "UPDATE" in sql_upper and "WHERE" not in sql_upper:
        return "BLOCK"

    if "INSERT INTO" in sql_upper:
        return "CONFIRM"

    if "DELETE FROM" in sql_upper:
        return "CONFIRM"

    if "UPDATE" in sql_upper:
        return "CONFIRM"

    return "ALLOW"

if __name__ == "__main__":
    sql = "UPDATE employees SET salary = 70000 WHERE department = 'IT';"

    decision = rule_filter(sql)

    print("SQL:", sql)
    print("Decision:", decision)