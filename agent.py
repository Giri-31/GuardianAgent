"""
agent.py

Simple GuardianAgent demo agent.

Generates SQL from a natural-language user request and executes it
only after GuardianAgent approves the operation.

Usage::

    python agent.py

Environment::

    GEMINI_API_KEY   – required for the SQL generation LLM call.
"""

import os
import sqlite3

# ============================================================
# Configuration
# ============================================================

_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATABASE = os.path.join(_DIR, "company.db")

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# ============================================================
# Client (lazy initialisation)
# ============================================================

_client = None


def _get_client():
    """Return a cached Gemini client, creating it on first call."""

    global _client

    if _client is not None:
        return _client

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai is required. Install it with: pip install google-genai"
        ) from exc

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set."
        )

    _client = genai.Client(api_key=api_key)
    return _client


def _safe_text(response):
    """
    Safely extract text from a Gemini response.

    Accessing response.text raises an exception when the model
    returns no output (e.g. safety filter block).  This helper
    extracts text via the candidates list first so that callers
    can handle empty responses without crashing.
    """

    try:
        # Try the fast path first.
        text = response.text
        if text:
            return text.strip()
    except Exception:
        pass

    # Walk candidates -> parts manually.
    try:
        for candidate in (response.candidates or []):
            for part in (candidate.content.parts or []):
                t = getattr(part, "text", None)
                if t:
                    return t.strip()
    except Exception:
        pass

    return ""


# ============================================================
# SQL generation
# ============================================================

def generate_sql(user_request):
    """
    Ask Gemini to convert a natural-language request into SQLite SQL.
    Returns only the SQL string.
    """

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

    client = _get_client()

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    text = _safe_text(response)

    if not text:
        raise RuntimeError(
            "Gemini returned an empty response. "
            "The request may have been blocked by safety filters."
        )

    return text


# ============================================================
# Query execution
# ============================================================

def execute_query(sql, database_path=None):
    """
    Execute a SQL statement against the project database and return rows.

    Parameters
    ----------
    sql:
        The SQL string to run.
    database_path:
        Optional path to the SQLite database.
        Defaults to company.db in the project root.
    """

    if database_path is None:
        database_path = DEFAULT_DATABASE

    connection = sqlite3.connect(database_path)
    cursor = connection.cursor()

    try:
        cursor.execute(sql)
        result = cursor.fetchall()
        connection.commit()
    finally:
        connection.close()

    return result


# ============================================================
# Demo
# ============================================================

def main():

    # Import Guardian here to avoid circular imports at module level.
    from guardian import guardian_check

    user_request = "Change Arun's salary to 70000."

    print("User request:", user_request)

    sql = generate_sql(user_request)

    print("Generated SQL:", sql)

    # --------------------------------------------------------
    # GuardianAgent safety check
    # --------------------------------------------------------

    check = guardian_check(user_request, sql)

    decision  = check["risk"]["decision"]
    risk_level = check["risk"]["risk_level"]

    print(f"Guardian decision : {decision}")
    print(f"Guardian risk     : {risk_level}")

    if decision == "ALLOW":

        result = execute_query(sql)

        print("Result:")
        for row in result:
            print(row)

    else:

        print("[BLOCKED] Guardian blocked the SQL execution.")
        print("Reason:", check["risk"].get("reason", "n/a"))


if __name__ == "__main__":
    main()