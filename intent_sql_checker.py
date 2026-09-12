from sql_analyzer import analyze_sql
from intent_analyzer import analyze_intent
from sql_analyzer import analyze_sql
from intent_analyzer import analyze_intent


def check_intent_sql(intent, sql_info):
    if intent["operation"] != sql_info["operation"]:
        return "MISMATCH"

    intended_scope = intent["scope"]

    if intended_scope == "single employee":
        target = intent["target"]
        where = sql_info["where"]

        if where is None:
            return "MISMATCH"

        if target.lower() not in where.lower():
            return "MISMATCH"

    return "MATCH"


if __name__ == "__main__":
    user_request = "Change Arun's salary to 70000."

    sql = "UPDATE employees SET salary = 70000 WHERE name = 'Arun';"

    intent = analyze_intent(user_request)

    sql_info = analyze_sql(sql)

    result = check_intent_sql(intent, sql_info)

    print("User request:", user_request)
    print("Intent:", intent)
    print("SQL:", sql)
    print("SQL analysis:", sql_info)
    print("Intent-SQL check:", result)