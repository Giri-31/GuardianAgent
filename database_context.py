import sqlite3


def analyze_database_impact(sql):
    sql_upper = sql.upper().strip()

    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    if sql_upper.startswith("SELECT"):
        impact_type = "READ"
        risk_level = "LOW"

    elif sql_upper.startswith("UPDATE"):
        impact_type = "DATA_MODIFICATION"

        if "WHERE" not in sql_upper:
            risk_level = "HIGH"
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM employees WHERE " +
                sql.split("WHERE", 1)[1].rstrip(";")
            )
            affected_rows = cursor.fetchone()[0]

            if affected_rows == 1:
                risk_level = "MEDIUM"
            elif affected_rows > 1:
                risk_level = "HIGH"
            else:
                risk_level = "LOW"

    elif sql_upper.startswith("DELETE"):
        impact_type = "DATA_DELETION"

        if "WHERE" not in sql_upper:
            risk_level = "CRITICAL"
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM employees WHERE " +
                sql.split("WHERE", 1)[1].rstrip(";")
            )
            affected_rows = cursor.fetchone()[0]

            if affected_rows == 1:
                risk_level = "HIGH"
            elif affected_rows > 1:
                risk_level = "CRITICAL"
            else:
                risk_level = "LOW"

    elif sql_upper.startswith("INSERT"):
        impact_type = "DATA_CREATION"
        risk_level = "MEDIUM"

    elif sql_upper.startswith("DROP"):
        impact_type = "SCHEMA_DESTRUCTION"
        risk_level = "CRITICAL"

    else:
        impact_type = "UNKNOWN"
        risk_level = "HIGH"

    connection.close()

    return {
        "impact_type": impact_type,
        "risk_level": risk_level
    }


if __name__ == "__main__":
    sql = "UPDATE employees SET salary = 70000 WHERE name = 'Arun';"

    impact = analyze_database_impact(sql)

    print("SQL:", sql)
    print("Database impact:", impact)