import re


def analyze_sql(sql):

    sql_clean = sql.strip()
    sql_lower = sql_clean.lower()

    operation_match = re.match(
        r"\s*(select|insert|update|delete|drop|alter|truncate)",
        sql_lower
    )

    if operation_match:
        operation = operation_match.group(1).upper()
    else:
        operation = "UNKNOWN"

    table = "unknown"

    table_match = re.search(
        r"\b(?:from|update|into|delete\s+from)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        sql_lower
    )

    if table_match:
        table = table_match.group(1)

    where_match = re.search(
        r"\bwhere\b(.*?)(?:;|$)",
        sql_lower,
        re.IGNORECASE
    )

    if where_match:
        where = where_match.group(1).strip()
        scope = "filtered"
    else:
        where = None
        scope = "all_rows"

    return {
        "operation": operation,
        "table": table,
        "where": where,
        "scope": scope,
        "sql": sql_clean
    }


if __name__ == "__main__":

    sql = "UPDATE employees SET salary = 70000 WHERE name = 'Arun';"

    result = analyze_sql(sql)

    print(result)