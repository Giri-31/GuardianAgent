import sqlite3

def create_database():
    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT,
            department TEXT,
            status TEXT,
            salary INTEGER
        )
    """)

    cursor.execute("DELETE FROM employees")

    employees = [
        (1, "Arun", "IT", "active", 60000),
        (2, "Meera", "HR", "active", 55000),
        (3, "Rahul", "IT", "inactive", 50000),
        (4, "Anu", "Finance", "active", 65000),
        (5, "Vishnu", "IT", "inactive", 52000)
    ]

    cursor.executemany(
        "INSERT INTO employees VALUES (?, ?, ?, ?, ?)",
        employees
    )

    connection.commit()
    connection.close()

    print("Database created successfully.")

def show_employees():
    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM employees")
    rows = cursor.fetchall()

    for row in rows:
        print(row)

    connection.close()


if __name__ == "__main__":
    create_database()
    show_employees()