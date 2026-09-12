import sqlite3


def analyze_scope(sql):
    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    sql_upper = sql.upper().strip()

    if "WHERE" not in sql_upper:
        connection.close()
        return "ALL_ROWS"

    try:
        cursor.execute(sql)
        rows = cursor.fetchall()
        row_count = len(rows)
    except:
        connection.close()
        return "UNKNOWN"

    connection.close()

    if row_count == 0:
        return "ZERO_ROWS"

    if row_count == 1:
        return "ONE_ROW"

    return "MULTIPLE_ROWS"


if __name__ == "__main__":
    sql = "SELECT * FROM employees WHERE department = 'IT';"

    scope = analyze_scope(sql)

    print("SQL:", sql)
    print("Scope:", scope)