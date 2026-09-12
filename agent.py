from google import genai
import os
import sqlite3

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

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


def execute_query(sql):
    connection = sqlite3.connect("company.db")
    cursor = connection.cursor()

    cursor.execute(sql)
    result = cursor.fetchall()

    connection.close()

    return result


user_request = "Change Arun's salary to 70000."

sql = generate_sql(user_request)

print("User request:", user_request)
print("Generated SQL:", sql)

result = execute_query(sql)

print("Result:")
for row in result:
    print(row)