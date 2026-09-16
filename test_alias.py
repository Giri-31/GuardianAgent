from guardian import guardian_check


# ============================================================
# TEST 1: SELECT with table alias
# ============================================================

result = guardian_check(
    "Please retrieve the salary for Arun.",
    "SELECT e.salary FROM employees AS e WHERE e.name = 'Arun';",
    known_intent={
        "operation": "SELECT",
        "target": "Arun",
        "field": "salary",
        "value": "unknown",
        "scope": "single employee"
    }
)

print("TEST 1 - SELECT ALIAS")
print("Scope:", result["scope"])
print("Decision:", result["risk"]["decision"])
print("Mismatches:", result["intent_sql"]["mismatches"])
print()


# ============================================================
# TEST 2: UPDATE with table alias
# ============================================================

result = guardian_check(
    "Change the salary of Arun to 55000.",
    "UPDATE employees AS e SET salary = 55000 WHERE e.name = 'Arun';",
    known_intent={
        "operation": "UPDATE",
        "target": "Arun",
        "field": "salary",
        "value": "55000",
        "scope": "single employee"
    }
)

print("TEST 2 - UPDATE ALIAS")
print("Scope:", result["scope"])
print("Decision:", result["risk"]["decision"])
print("Mismatches:", result["intent_sql"]["mismatches"])
print()


# ============================================================
# TEST 3: INSERT
# ============================================================

result = guardian_check(
    "Add a new employee named TestUser with salary 50000.",
    "INSERT INTO employees (name, salary, department) "
    "VALUES ('TestUser', 50000, 'Engineering');",
    known_intent={
        "operation": "INSERT",
        "target": "TestUser",
        "field": "salary",
        "value": "50000",
        "scope": "single employee"
    }
)

print("TEST 3 - INSERT")
print("Scope:", result["scope"])
print("Decision:", result["risk"]["decision"])
print("Mismatches:", result["intent_sql"]["mismatches"])
print()


print("=" * 60)
print("TESTING COMPLETE")
print("=" * 60)