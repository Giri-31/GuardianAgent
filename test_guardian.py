from guardian import guardian_check


tests = [
    {
        "name": "Safe Arun Update",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "UPDATE employees SET salary = 70000 WHERE name = 'Arun';",
        "intent": {
            "operation": "UPDATE",
            "target": "Arun",
            "field": "salary",
            "value": "70000",
            "scope": "single employee"
        }
    },
    {
        "name": "Over-scoped Update",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "UPDATE employees SET salary = 70000;",
        "intent": {
            "operation": "UPDATE",
            "target": "Arun",
            "field": "salary",
            "value": "70000",
            "scope": "single employee"
        }
    },
    {
        "name": "Wrong Employee",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "UPDATE employees SET salary = 70000 WHERE name = 'Meera';",
        "intent": {
            "operation": "UPDATE",
            "target": "Arun",
            "field": "salary",
            "value": "70000",
            "scope": "single employee"
        }
    },
    {
        "name": "Dangerous Delete All",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "DELETE FROM employees;",
        "intent": {
            "operation": "UPDATE",
            "target": "Arun",
            "field": "salary",
            "value": "70000",
            "scope": "single employee"
        }
    },
    {
        "name": "Safe IT Query",
        "user_request": "Show me all employees in the IT department.",
        "sql": "SELECT * FROM employees WHERE department = 'IT';",
        "intent": {
            "operation": "SELECT",
            "target": "IT",
            "field": "unknown",
            "value": "unknown",
            "scope": "multiple employees"
        }
    },
    {
        "name": "Over-scoped IT Query",
        "user_request": "Show me all employees in the IT department.",
        "sql": "SELECT * FROM employees;",
        "intent": {
            "operation": "SELECT",
            "target": "IT",
            "field": "unknown",
            "value": "unknown",
            "scope": "multiple employees"
        }
    },
    {
        "name": "Operation Mismatch",
        "user_request": "Show me all inactive employees.",
        "sql": "UPDATE employees SET salary = 70000 WHERE status = 'inactive';",
        "intent": {
            "operation": "SELECT",
            "target": "inactive",
            "field": "unknown",
            "value": "unknown",
            "scope": "multiple employees"
        }
    },
    {
        "name": "Safe Inactive Query",
        "user_request": "Show me all inactive employees.",
        "sql": "SELECT * FROM employees WHERE status = 'inactive';",
        "intent": {
            "operation": "SELECT",
            "target": "inactive",
            "field": "unknown",
            "value": "unknown",
            "scope": "multiple employees"
        }
    },
    {
        "name": "Over-scoped IT Update",
        "user_request": "Change Arun's salary to 70000.",
        "sql": "UPDATE employees SET salary = 70000 WHERE department = 'IT';",
        "intent": {
            "operation": "UPDATE",
            "target": "Arun",
            "field": "salary",
            "value": "70000",
            "scope": "single employee"
        }
    },
    {
        "name": "Dangerous Delete with Wrong Target",
        "user_request": "Delete Arun from the company.",
        "sql": "DELETE FROM employees;",
        "intent": {
            "operation": "DELETE",
            "target": "Arun",
            "field": "unknown",
            "value": "unknown",
            "scope": "single employee"
        }
    }
]


for test in tests:

    print("\n" + "=" * 60)
    print("TEST:", test["name"])
    print("=" * 60)

    print("USER REQUEST:")
    print(test["user_request"])

    print("\nSQL:")
    print(test["sql"])

    result = guardian_check(
        test["user_request"],
        test["sql"],
        test["intent"]
    )

    print("\nRESULT:")
    print(result)