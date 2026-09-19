import os
from dbbench_loader import load_dbbench


MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


def _get_client():
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required. pip install google-genai"
        ) from exc
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=api_key)


def _safe_text(response):
    """Safely extract text from a Gemini response without crashing on empty output."""
    try:
        text = response.text
        if text:
            return text.strip()
    except Exception:
        pass
    try:
        for candidate in (response.candidates or []):
            for part in (candidate.content.parts or []):
                t = getattr(part, "text", None)
                if t:
                    return t.strip()
    except Exception:
        pass
    return ""


client = _get_client()


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
        model=MODEL,
        contents=prompt
    )

    text = _safe_text(response)

    if not text:
        raise RuntimeError(
            "Gemini returned an empty response. Request may have been blocked."
        )

    return text


tasks = load_dbbench()[:5]

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