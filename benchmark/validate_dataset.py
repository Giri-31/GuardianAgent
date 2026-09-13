import json
import re
import sqlite3
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

DATASET_FILE = BASE_DIR / "generated_dataset.json"
DB_FILE = PROJECT_DIR / "company.db"


# ============================================================
# VALID VALUES
# ============================================================

VALID_DECISIONS = {
    "ALLOW",
    "CONFIRM",
    "BLOCK"
}

VALID_CATEGORIES = {
    "SAFE",
    "TARGET_MISMATCH",
    "FIELD_MISMATCH",
    "OPERATION_MISMATCH",
    "SCOPE_MISMATCH",
    "OVER_SCOPED_READ",
    "MULTI_ROW_WRITE",
    "DANGEROUS_OPERATION",
    "COMBINATION"
}

VALID_OPERATIONS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "UNKNOWN"
}

REQUIRED_FIELDS = {
    "id",
    "user_intent",
    "generated_sql",
    "operation",
    "target_table",
    "target_columns",
    "scope",
    "database_context",
    "expected_decision",
    "category",
    "reason"
}


# ============================================================
# DATABASE
# ============================================================

def load_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, department, status, salary
        FROM employees
        ORDER BY id
    """)

    rows = cursor.fetchall()

    conn.close()

    employees = []

    for row in rows:
        employees.append({
            "id": row[0],
            "name": row[1],
            "department": row[2],
            "status": row[3],
            "salary": row[4]
        })

    return employees


# ============================================================
# SQL OPERATION EXTRACTION
# ============================================================

def extract_operation(sql):
    """
    Extract the first SQL operation.
    """

    sql_clean = sql.strip().upper()

    match = re.match(
        r"^(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)\b",
        sql_clean
    )

    if match:
        return match.group(1)

    return "UNKNOWN"


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_dataset():

    print("=" * 70)
    print("GUARDIANAGENT DATASET VALIDATION")
    print("=" * 70)

    print()
    print(f"Dataset: {DATASET_FILE}")
    print(f"Database: {DB_FILE}")

    # --------------------------------------------------------
    # Load dataset
    # --------------------------------------------------------

    try:
        with open(
            DATASET_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            dataset = json.load(f)

    except Exception as e:
        print()
        print(f"ERROR: Could not load dataset: {e}")
        return False

    # --------------------------------------------------------
    # Load database
    # --------------------------------------------------------

    try:
        employees = load_database()

    except Exception as e:
        print()
        print(f"ERROR: Could not load database: {e}")
        return False

    print()
    print(f"Dataset cases: {len(dataset)}")
    print(f"Database employees: {len(employees)}")

    # --------------------------------------------------------
    # Database reference values
    # --------------------------------------------------------

    employee_names = {
        employee["name"]
        for employee in employees
    }

    departments = {
        employee["department"]
        for employee in employees
    }

    valid_columns = {
        "id",
        "name",
        "department",
        "status",
        "salary"
    }

    # --------------------------------------------------------
    # Validation containers
    # --------------------------------------------------------

    errors = []
    warnings = []

    category_counts = {}
    decision_counts = {}

    seen_ids = set()

    # ========================================================
    # CASE VALIDATION
    # ========================================================

    for index, case in enumerate(dataset, start=1):

        case_id = case.get(
            "id",
            f"UNKNOWN_{index}"
        )

        # ----------------------------------------------------
        # Required fields
        # ----------------------------------------------------

        missing_fields = REQUIRED_FIELDS - set(case.keys())

        if missing_fields:

            errors.append(
                f"[ERROR] {case_id}: missing fields "
                f"{sorted(missing_fields)}."
            )

            continue

        # ----------------------------------------------------
        # Duplicate IDs
        # ----------------------------------------------------

        if case_id in seen_ids:

            errors.append(
                f"[ERROR] {case_id}: duplicate case ID."
            )

        seen_ids.add(case_id)

        # ----------------------------------------------------
        # Decision validation
        # ----------------------------------------------------

        decision = case["expected_decision"]

        if decision not in VALID_DECISIONS:

            errors.append(
                f"[ERROR] {case_id}: "
                f"invalid decision '{decision}'."
            )

        else:

            decision_counts[decision] = (
                decision_counts.get(decision, 0) + 1
            )

        # ----------------------------------------------------
        # Category validation
        # ----------------------------------------------------

        category = case["category"]

        if category not in VALID_CATEGORIES:

            errors.append(
                f"[ERROR] {case_id}: "
                f"invalid category '{category}'."
            )

        else:

            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )

        # ----------------------------------------------------
        # Operation validation
        # ----------------------------------------------------

        operation = case["operation"]

        if operation not in VALID_OPERATIONS:

            errors.append(
                f"[ERROR] {case_id}: "
                f"invalid operation '{operation}'."
            )

        # ----------------------------------------------------
        # SQL operation consistency
        # ----------------------------------------------------

        sql_operation = extract_operation(
            case["generated_sql"]
        )

        if sql_operation != operation:

            errors.append(
                f"[ERROR] {case_id}: "
                f"recorded operation '{operation}' "
                f"does not match SQL operation "
                f"'{sql_operation}'."
            )

        # ----------------------------------------------------
        # Target table
        # ----------------------------------------------------

        if case["target_table"] != "employees":

            errors.append(
                f"[ERROR] {case_id}: "
                f"invalid target table "
                f"'{case['target_table']}'."
            )

        # ----------------------------------------------------
        # Target columns
        # ----------------------------------------------------

        target_columns = case["target_columns"]

        if not isinstance(target_columns, list):

            errors.append(
                f"[ERROR] {case_id}: "
                f"target_columns must be a list."
            )

        else:

            for column in target_columns:

                if column not in valid_columns:

                    errors.append(
                        f"[ERROR] {case_id}: "
                        f"invalid target column "
                        f"'{column}'."
                    )

        # ----------------------------------------------------
        # SQL references employees
        # ----------------------------------------------------

        sql_lower = case["generated_sql"].lower()

        if "employees" not in sql_lower:

            errors.append(
                f"[ERROR] {case_id}: "
                f"SQL does not reference employees table."
            )

        # ----------------------------------------------------
        # Employee name validation
        # ----------------------------------------------------

        intent = case["user_intent"]

        mentioned_names = []

        for name in employee_names:

            if name.lower() in intent.lower():

                mentioned_names.append(name)

        # ----------------------------------------------------
        # Department validation
        # ----------------------------------------------------

        for department in departments:

            if department.lower() in intent.lower():
                break

        # ----------------------------------------------------
        # Category / decision sanity checks
        # ----------------------------------------------------

        if category == "SAFE" and decision != "ALLOW":

            errors.append(
                f"[ERROR] {case_id}: "
                f"SAFE case should have ALLOW decision."
            )

        if category == "DANGEROUS_OPERATION" and decision != "BLOCK":

            errors.append(
                f"[ERROR] {case_id}: "
                f"DANGEROUS_OPERATION should have BLOCK decision."
            )

        if category == "COMBINATION" and decision != "BLOCK":

            errors.append(
                f"[ERROR] {case_id}: "
                f"COMBINATION cases should have BLOCK decision."
            )

        if category == "TARGET_MISMATCH" and decision != "BLOCK":

            errors.append(
                f"[ERROR] {case_id}: "
                f"TARGET_MISMATCH should have BLOCK decision."
            )

        if category == "FIELD_MISMATCH" and decision != "BLOCK":

            errors.append(
                f"[ERROR] {case_id}: "
                f"FIELD_MISMATCH should have BLOCK decision."
            )

        if category == "OPERATION_MISMATCH" and decision != "BLOCK":

            errors.append(
                f"[ERROR] {case_id}: "
                f"OPERATION_MISMATCH should have BLOCK decision."
            )

        if category == "SCOPE_MISMATCH" and decision != "BLOCK":

            errors.append(
                f"[ERROR] {case_id}: "
                f"SCOPE_MISMATCH should have BLOCK decision."
            )

        if category == "OVER_SCOPED_READ" and decision != "CONFIRM":

            errors.append(
                f"[ERROR] {case_id}: "
                f"OVER_SCOPED_READ should have CONFIRM decision."
            )

        if category == "MULTI_ROW_WRITE" and decision != "CONFIRM":

            errors.append(
                f"[ERROR] {case_id}: "
                f"MULTI_ROW_WRITE should have CONFIRM decision."
            )

    # ========================================================
    # RESULTS
    # ========================================================

    print()
    print("=" * 70)
    print("CATEGORY DISTRIBUTION")
    print("-" * 40)

    for category in sorted(category_counts):

        print(
            f"{category:25s}"
            f"{category_counts[category]}"
        )

    print()
    print("DECISION DISTRIBUTION")
    print("-" * 40)

    for decision in sorted(decision_counts):

        print(
            f"{decision:25s}"
            f"{decision_counts[decision]}"
        )

    print()
    print("=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)

    print()
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    if errors:

        print()
        print("ERRORS")
        print("-" * 40)

        for error in errors:
            print(error)

        print()
        print("=" * 70)
        print("RESULT: DATASET INVALID")
        print("Fix the errors before using this dataset.")
        print("=" * 70)

        return False

    print()
    print("=" * 70)
    print("RESULT: DATASET VALID")
    print("No validation problems detected.")
    print("=" * 70)

    return True


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    success = validate_dataset()

    if not success:
        raise SystemExit(1)