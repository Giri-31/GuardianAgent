from google import genai
import os

from dbbench_loader import load_dbbench


client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def generate_sql(task):

    table_info = task["table"]

    prompt = f"""
You are a database assistant.

Convert the user's request into exactly one SQL query.

User request:
{task["description"]}

Database table information:
{table_info}

Rules:
- Return ONLY the SQL query.
- Do not use markdown.
- Do not explain anything.
"""

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )

    return response.text.strip()


tasks = load_dbbench()

task = tasks[0]

print("=" * 60)
print("DBBench TASK 1")
print("=" * 60)

print()
print("USER REQUEST:")
print(task["description"])

print()
print("REFERENCE SQL:")
print(task["sql"])

print()
print("GENERATED SQL:")

generated_sql = generate_sql(task)

print(generated_sql)