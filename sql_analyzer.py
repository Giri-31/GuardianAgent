import re


def analyze_sql(sql):
    sql = sql.strip()

    operation = sql.split()[0].upper()

    table_match = re.search(
        r'\b(?:FROM|UPDATE|INTO)\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        sql,
        re.IGNORECASE
    )

    table = table_match.group(1) if table_match else None

    where_match = re.search(
        r'\bWHERE\b(.*?)(?:;|$)',
        sql,
        re.IGNORECASE
    )

    where = where_match.group(1).strip() if where_match else None

    if where:
        scope = "filtered"
    else:
        scope = "all_rows"

    return {
        "operation": operation,
        "table": table,
        "where": where,
        "scope": scope
    }


sql = "UPDATE employees SET salary = 70000 WHERE name = 'Arun';"

info = analyze_sql(sql)

print(info)