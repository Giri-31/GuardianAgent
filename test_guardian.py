from guardian import guardian_check


tests = [
    {
        "name": "Safe SQL",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "UPDATE employees SET salary = 70000 WHERE name = 'Arun';"
    },
    {
        "name": "Over-scoped SQL",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "UPDATE employees SET salary = 70000;"
    },
    {
        "name": "Dangerous DELETE",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "DELETE FROM employees;"
    }
]


for test in tests:

    print("\n==============================")
    print(test["name"])
    print("==============================")

    result = guardian_check(
        test["user_request"],
        test["sql"]
    )

    print("User request:", test["user_request"])
    print("SQL:", test["sql"])
    print("Intent:", result["intent"])
    print("SQL analysis:", result["sql_info"])
    print("Scope:", result["scope"])
    print("Impact:", result["impact"])
    print("Risk:", result["risk"])