from google import genai
import os
import sqlite3

from sql_analyzer import analyze_sql
from intent_analyzer import analyze_intent
from risk_engine import calculate_risk
from intent_sql_checker import check_intent_sql

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def generate_sql(user_request):
    prompt = f"""
You are a SQL generator.

Database:
Table: employees

Columns:
id INTEGER
name TEXT
department TEXT
status TEXT
salary INTEGER

Convert the user's request into a SQLite SQL query.

User request:
{user_request}

Return ONLY the SQL query.
Do not use markdown.
Do not explain anything.
"""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )

    return response.text.strip()


def analyze_scope_safely(sql):
    sql_upper = sql.upper().strip()

    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    try:
        if "WHERE" not in sql_upper:
            cursor.execute("SELECT COUNT(*) FROM employees")
        else:
            where_condition = sql.split("WHERE", 1)[1].rstrip(";")

            cursor.execute(
                "SELECT COUNT(*) FROM employees WHERE " + where_condition
            )

        count = cursor.fetchone()[0]

    except:
        connection.close()
        return "UNKNOWN"

    connection.close()

    if count == 0:
        return "ZERO_ROWS"

    if count == 1:
        return "ONE_ROW"

    return "MULTIPLE_ROWS"


def analyze_impact(sql, scope):
    operation = sql.split()[0].upper()

    if operation == "SELECT":
        return {
            "impact_type": "READ",
            "risk_level": "LOW"
        }

    if operation == "INSERT":
        return {
            "impact_type": "DATA_CREATION",
            "risk_level": "MEDIUM"
        }

    if operation == "UPDATE":
        if scope == "ONE_ROW":
            risk = "MEDIUM"
        elif scope == "MULTIPLE_ROWS":
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        return {
            "impact_type": "DATA_MODIFICATION",
            "risk_level": risk
        }

    if operation == "DELETE":
        if scope == "ONE_ROW":
            risk = "HIGH"
        else:
            risk = "CRITICAL"

        return {
            "impact_type": "DATA_DELETION",
            "risk_level": risk
        }

    if operation == "DROP":
        return {
            "impact_type": "SCHEMA_DESTRUCTION",
            "risk_level": "CRITICAL"
        }

    return {
        "impact_type": "UNKNOWN",
        "risk_level": "HIGH"
    }


def guardian_check(user_request, sql, known_intent=None):
    if known_intent is not None:
        intent = known_intent
    else:
        intent = analyze_intent(user_request)

    sql_info = analyze_sql(sql)

    scope = analyze_scope_safely(sql)

    impact = analyze_impact(sql, scope)

    intent_sql_result = check_intent_sql(
    intent,
    sql_info,
    scope
)

    risk = calculate_risk(
    intent,
    sql_info,
    scope,
    impact,
    intent_sql_result
)

    return {
        "intent": intent,
        "sql_info": sql_info,
        "scope": scope,
        "impact": impact,
        "intent_sql": intent_sql_result,
        "risk": risk
    }


def execute_query(sql):
    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    cursor.execute(sql)

    if sql.strip().upper().startswith("SELECT"):
        result = cursor.fetchall()
    else:
        connection.commit()
        result = []

    connection.close()

    return result


def execute_with_guardian(user_request, sql):
    result = guardian_check(user_request, sql)

    decision = result["risk"]["decision"]

    print("\nGUARDIAN DECISION:", decision)

    if decision == "BLOCK":
        print("SQL BLOCKED.")
        return None

    if decision == "CONFIRM":
        print("SQL requires user confirmation.")

        answer = input("Do you want to execute this SQL? (yes/no): ")

        if answer.lower() != "yes":
            print("SQL execution cancelled.")
            return None

    if decision == "ALLOW":
        print("SQL automatically allowed.")

    print("Executing SQL...")

    return execute_query(sql)


if __name__ == "__main__":

    user_request = "Change Arun's salary to 70000."

    sql = generate_sql(user_request)

    print("\nUSER REQUEST:")
    print(user_request)

    print("\nGENERATED SQL:")
    print(sql)

    result = execute_with_guardian(
        user_request,
        sql
    )

    if result is not None:
        print("\nRESULT:")

        for row in result:
            print(row)