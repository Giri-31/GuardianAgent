import sqlite3


def analyze_scope(sql):

    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    sql_upper = sql.upper().strip()

    if "WHERE" not in sql_upper:

        connection.close()
        return "ALL_ROWS"

    try:

        if sql_upper.startswith("SELECT"):

            cursor.execute(sql)
            rows = cursor.fetchall()
            row_count = len(rows)

        elif sql_upper.startswith("UPDATE"):

            where_clause = sql.split("WHERE", 1)[1].strip().rstrip(";")

            query = "SELECT COUNT(*) FROM employees WHERE " + where_clause

            cursor.execute(query)
            row_count = cursor.fetchone()[0]

        elif sql_upper.startswith("DELETE"):

            where_clause = sql.split("WHERE", 1)[1].strip().rstrip(";")

            query = "SELECT COUNT(*) FROM employees WHERE " + where_clause

            cursor.execute(query)
            row_count = cursor.fetchone()[0]

        else:

            connection.close()
            return "UNKNOWN"

    except Exception:
        connection.close()
        return "UNKNOWN"

    connection.close()

    if row_count == 0:
        return "ZERO_ROWS"

    if row_count == 1:
        return "ONE_ROW"

    return "MULTIPLE_ROWS"


if __name__ == "__main__":

    sql = "UPDATE employees SET salary = salary + 5000 WHERE department = 'HR';"

    scope = analyze_scope(sql)

    print("SQL:", sql)
    print("Scope:", scope)