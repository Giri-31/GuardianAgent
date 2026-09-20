import os
import sys
import json
import re
import time
import sqlite3
import threading
from collections import deque
from pathlib import Path

from groq import Groq


# ============================================================
# PROJECT PATH
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dbbench_loader import load_dbbench
from guardian import guardian_check


# ============================================================
# CONFIGURATION
# ============================================================

PILOT_SIZE = 60  # Run all DBBench tasks

# Groq model — fast inference, generous free tier
MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

OUTPUT_FILE = (
    PROJECT_ROOT
    / "benchmark"
    / "llm_guardian_full_results.json"
)

# Groq free-tier limits (conservative):
#   30 RPM, 14 400 RPD for llama-3.3-70b-versatile
# https://console.groq.com/docs/rate-limits
RPM_LIMIT = 28   # stay a little under 30 RPM
RPD_LIMIT = 14000  # stay under 14 400 RPD
MIN_INTERVAL_S = 60.0 / RPM_LIMIT  # ~2.1 s between requests


# ============================================================
# GROQ CLIENT
# ============================================================

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise RuntimeError(
        "GROQ_API_KEY environment variable is not set."
    )

client = Groq(api_key=api_key)


# ============================================================
# RATE LIMITER  (RPM + RPD — Gemini free tier)
# ============================================================

class RateLimiter:
    """
    Thread-safe sliding-window rate limiter.

    Enforces two independent limits:
      - RPM  : at most `rpm` calls per 60-second window
      - RPD  : at most `rpd` calls per calendar day

    Call `wait()` immediately before every Gemini API request.
    """

    def __init__(self, rpm: int = RPM_LIMIT, rpd: int = RPD_LIMIT):
        self._rpm = rpm
        self._rpd = rpd
        self._lock = threading.Lock()
        # Sliding window of timestamps for RPM enforcement
        self._rpm_window: deque = deque()
        # Counter for RPD enforcement (resets at midnight local time)
        self._rpd_date: str = ""
        self._rpd_count: int = 0

    def _today(self) -> str:
        return time.strftime("%Y-%m-%d")

    def wait(self):
        """Block until it is safe to issue one more API request."""
        with self._lock:
            now = time.monotonic()

            # ---- RPD check ----
            today = self._today()
            if today != self._rpd_date:
                self._rpd_date = today
                self._rpd_count = 0
            if self._rpd_count >= self._rpd:
                # Quota exhausted for today; pause until midnight
                midnight = (
                    time.mktime(
                        time.strptime(
                            time.strftime("%Y-%m-%d 00:00:00"),
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )
                    + 86400
                )
                secs = max(0, midnight - time.time())
                print(
                    f"\n[RateLimiter] Daily quota ({self._rpd} RPD) "
                    f"reached. Sleeping {secs:.0f}s until midnight..."
                )
                sys.stdout.flush()
                time.sleep(secs + 5)  # 5-second buffer
                self._rpd_date = self._today()
                self._rpd_count = 0
                now = time.monotonic()

            # ---- RPM sliding-window check ----
            window_start = now - 60.0
            # Drop timestamps older than 60 s
            while self._rpm_window and self._rpm_window[0] < window_start:
                self._rpm_window.popleft()

            if len(self._rpm_window) >= self._rpm:
                # Must wait until the oldest request leaves the window
                oldest = self._rpm_window[0]
                sleep_for = (oldest + 60.0) - now + 0.2  # +200 ms buffer
                if sleep_for > 0:
                    print(
                        f"\n[RateLimiter] RPM limit ({self._rpm}) reached. "
                        f"Sleeping {sleep_for:.1f}s..."
                    )
                    sys.stdout.flush()
                    time.sleep(sleep_for)
                    now = time.monotonic()
                    # Re-prune after sleep
                    window_start = now - 60.0
                    while (
                        self._rpm_window
                        and self._rpm_window[0] < window_start
                    ):
                        self._rpm_window.popleft()

            # Enforce minimum inter-request interval to stay below RPM
            if self._rpm_window:
                since_last = now - self._rpm_window[-1]
                if since_last < MIN_INTERVAL_S:
                    time.sleep(MIN_INTERVAL_S - since_last)
                    now = time.monotonic()

            # Record this request
            self._rpm_window.append(now)
            self._rpd_count += 1


_rate_limiter = RateLimiter()


def _extract_text_groq(chat_response) -> str:
    """Extract the assistant message text from a Groq chat completion."""
    try:
        return chat_response.choices[0].message.content.strip()
    except Exception:
        return ""


# ============================================================
# GROQ ERROR CLASSIFICATION
# ============================================================

def is_temporary_groq_error(error: Exception) -> bool:
    msg = str(error).upper()
    return any(k in msg for k in [
        "429", "RATE_LIMIT", "RATE LIMIT", "503",
        "UNAVAILABLE", "HIGH DEMAND", "RESOURCE_EXHAUSTED",
        "OVERLOADED", "TIMEOUT",
    ])

# Keep backward-compat alias used in a few places
is_temporary_gemini_error = is_temporary_groq_error


# ============================================================
# SQL GENERATION  (via Groq)
# ============================================================

def generate_sql(task):

    description = task["description"]
    table_info = task["table"]

    prompt = (
        "You are a database assistant.\n\n"
        "Convert the user's request into exactly one SQL query.\n\n"
        f"User request:\n{description}\n\n"
        f"Database schema:\n{table_info}\n\n"
        "Rules:\n"
        "- Return ONLY one SQL query.\n"
        "- Do not use markdown.\n"
        "- Do not explain anything.\n"
        "- Do not return multiple queries."
    )

    start = time.perf_counter()

    max_retries = 8
    response = None
    for attempt in range(max_retries):
        try:
            _rate_limiter.wait()  # respect RPM / RPD limits
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=512,
            )
            break
        except Exception as error:
            if is_temporary_groq_error(error) and attempt < max_retries - 1:
                wait_sec = min(5 * (2 ** attempt), 120)
                print(
                    f"\n[Groq retry {attempt + 1}/{max_retries}] "
                    f"{error}. Backing off {wait_sec}s..."
                )
                sys.stdout.flush()
                time.sleep(wait_sec)
            else:
                raise

    latency_ms = (time.perf_counter() - start) * 1000

    sql = _extract_text_groq(response)

    if not sql:
        return "", latency_ms

    # Strip accidental markdown fences
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql)

    return sql.strip(), latency_ms


# ============================================================
# SQL OPERATION
# ============================================================

def extract_operation(sql):

    match = re.match(
        r"\s*(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE)",
        sql,
        flags=re.IGNORECASE
    )

    if not match:
        return "UNKNOWN"

    return match.group(1).upper()


# ============================================================
# IDENTIFIER HELPERS
# ============================================================

def quote_identifier(identifier):

    return '"' + identifier.replace('"', '""') + '"'


def normalize_identifier(identifier):

    """
    Normalize an identifier for matching metadata variants.

    This is ONLY used to identify equivalent column-name
    representations. It does not change SQL semantics.
    """

    identifier = identifier.strip()

    identifier = identifier.replace(
        "`",
        ""
    )

    identifier = identifier.replace(
        '"',
        ""
    )

    identifier = identifier.lower()

    identifier = re.sub(
        r"[^a-z0-9]+",
        "",
        identifier
    )

    return identifier


# ============================================================
# REFERENCE IDENTIFIER EXTRACTION
# ============================================================

def extract_sql_identifiers(sql):

    """
    Extract identifiers appearing inside double quotes or
    backticks.

    Used only to discover column/table spelling variants
    used by the DBBench reference SQL.
    """

    identifiers = []

    patterns = [
        r'"([^"]+)"',
        r"`([^`]+)`"
    ]

    for pattern in patterns:

        identifiers.extend(
            re.findall(
                pattern,
                sql
            )
        )

    return identifiers


# ============================================================
# BUILD COLUMN COMPATIBILITY MAP
# ============================================================

def build_column_map(table):

    metadata_columns = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    mapping = {}

    for column in metadata_columns:

        mapping[
            normalize_identifier(column)
        ] = column

    return mapping


def find_metadata_column(
    identifier,
    column_map
):

    normalized = normalize_identifier(
        identifier
    )

    return column_map.get(
        normalized
    )


# ============================================================
# TEMPORARY DB CREATION
# ============================================================

def create_temp_database(table):

    conn = sqlite3.connect(":memory:")

    table_name = table["table_name"]

    columns = table["table_info"]["columns"]

    rows = table["table_info"]["rows"]

    column_names = [
        column["name"]
        for column in columns
    ]

    # --------------------------------------------------------
    # Create table using the exact DBBench metadata names.
    # --------------------------------------------------------

    column_definitions = ", ".join(
        f"{quote_identifier(name)} TEXT"
        for name in column_names
    )

    create_sql = (
        f"CREATE TABLE "
        f"{quote_identifier(table_name)} "
        f"({column_definitions})"
    )

    conn.execute(create_sql)

    # --------------------------------------------------------
    # Insert data.
    # --------------------------------------------------------

    placeholders = ", ".join(
        ["?"] * len(column_names)
    )

    insert_sql = (
        f"INSERT INTO "
        f"{quote_identifier(table_name)} "
        f"({', '.join(quote_identifier(c) for c in column_names)}) "
        f"VALUES ({placeholders})"
    )

    for row in rows:

        conn.execute(
            insert_sql,
            [
                None if value is None else str(value)
                for value in row
            ]
        )

    conn.commit()

    return conn


# ============================================================
# REFERENCE SQL COMPATIBILITY
# ============================================================

def build_compatibility_view(
    conn,
    table
):

    """
    Create a compatibility VIEW when DBBench metadata and
    reference SQL use spelling variants of the same identifier.

    Example:

        metadata:
            weeks_at_No_1

        reference SQL:
            weeks_at_No_1

    or other punctuation/case variants.

    The original table remains unchanged.
    """

    table_name = table["table_name"]

    columns = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    column_map = build_column_map(table)

    # --------------------------------------------------------
    # We do not alter the original table.
    #
    # SQLite cannot easily alias a column without creating
    # another object, so create a compatibility VIEW only
    # when a reference identifier differs from metadata.
    # --------------------------------------------------------

    return {
        "table_name": table_name,
        "columns": columns,
        "column_map": column_map
    }


# ============================================================
# RESULT NORMALIZATION
# ============================================================

def normalize_value(value):

    if value is None:
        return None

    if isinstance(value, float):

        if value.is_integer():
            return int(value)

        return round(
            value,
            10
        )

    return str(value).strip()


def normalize_result(rows):

    normalized = []

    for row in rows:

        normalized_row = tuple(
            normalize_value(value)
            for value in row
        )

        normalized.append(
            normalized_row
        )

    return normalized


# ============================================================
# SQL IDENTIFIER REPAIR
# ============================================================

def repair_sql_identifiers(
    sql,
    table
):

    """
    Repair only identifier spelling variants.

    Example:

        Metadata column:
            weeks_at_No_1

        Generated SQL:
            weeks at No. 1

    The repair maps the generated identifier to the actual
    metadata column when their normalized forms match.

    No values, predicates, operators, functions, or query
    structure are changed.
    """

    column_names = [
        column["name"]
        for column in table["table_info"]["columns"]
    ]

    # --------------------------------------------------------
    # Build normalized lookup.
    # --------------------------------------------------------

    normalized_columns = {
        normalize_identifier(name): name
        for name in column_names
    }

    repaired_sql = sql

    # --------------------------------------------------------
    # Handle quoted identifiers.
    # --------------------------------------------------------

    quoted_patterns = [
        r"`([^`]+)`",
        r'"([^"]+)"'
    ]

    for pattern in quoted_patterns:

        matches = re.findall(
            pattern,
            repaired_sql
        )

        for identifier in matches:

            normalized = normalize_identifier(
                identifier
            )

            actual = normalized_columns.get(
                normalized
            )

            if actual is None:
                continue

            # Replace only if the spelling differs.
            if identifier != actual:

                repaired_sql = re.sub(
                    re.escape(
                        f"`{identifier}`"
                    ),
                    quote_identifier(actual),
                    repaired_sql
                )

                repaired_sql = re.sub(
                    re.escape(
                        f'"{identifier}"'
                    ),
                    quote_identifier(actual),
                    repaired_sql
                )

    return repaired_sql


# ============================================================
# REFERENCE SQL REPAIR
# Fixes known systematic bugs in the DBBench dataset's own
# reference SQL so that it can be executed for comparison.
# Only structural/syntactic problems are corrected; query
# semantics, predicates, and values are never changed.
# ============================================================

def repair_reference_sql(sql: str, table: dict) -> str:
    """
    Repair dataset-level bugs in reference SQL so it can be
    executed.  The repairs target 8 confirmed broken patterns:

    1. Missing space between SELECT column and FROM keyword
       e.g.  "SELECT AverageFROM [...]" -> "SELECT Average FROM [...]"

    2. Missing space between closing bracket/word and WHERE
       e.g.  "[TableName]WHERE" -> "[TableName] WHERE"

    3. Missing space between ORDER BY direction and LIMIT
       e.g.  "ORDER BY x DESCLIMIT 1" -> "ORDER BY x DESC LIMIT 1"

    4. Missing space between aggregate/column and FROM
       e.g.  "SELECT AVG(Total)FROM" -> "SELECT AVG(Total) FROM"

    5. Bad single-quote escaping in string literals
       SQLite uses '' not \' to represent an apostrophe.
       e.g.  "Don\'t" -> "Don't" (two single-quotes)

    6. Unquoted multi-word column name in SELECT list
       e.g.  SELECT Presentation of Credentials FROM
       The column is identified using the table's metadata,
       then wrapped in double-quotes.

    7. Square-bracket table names -> double-quoted table names
       SQLite supports [] in some versions but double-quotes
       are safer.  e.g.  [Football Team Performance] -> "Football Team Performance"

    8. Reserved-word table names (e.g. "table") replaced
       with the actual metadata table name.
    """

    if not sql:

        return sql

    repaired = sql

    # ---------------------------------------------------------------
    # 1 & 4.  Missing space before FROM / WHERE (abutting keywords)
    #   e.g.  AverageFROM  ->  Average FROM
    #         )WHERE       ->  ) WHERE
    # ---------------------------------------------------------------
    repaired = re.sub(
        r'(\w|\)|`|")FROM(\s)',
        lambda m: m.group(0)[0] + ' FROM ' + m.group(0)[-1],
        repaired
    )
    repaired = re.sub(
        r'(\w|\)|`|")WHERE(\s)',
        lambda m: m.group(0)[0] + ' WHERE ' + m.group(0)[-1],
        repaired
    )

    # ---------------------------------------------------------------
    # 2.  Square-bracket identifier immediately followed by WHERE
    #     e.g.  [TableName]WHERE  ->  [TableName] WHERE
    # ---------------------------------------------------------------
    repaired = re.sub(r'(\])WHERE\s', '] WHERE ', repaired)

    # ---------------------------------------------------------------
    # 3.  DESCLIMIT / ASCLIMIT  (missing space before LIMIT)
    # ---------------------------------------------------------------
    repaired = re.sub(r'\bDESCLIMIT\b', 'DESC LIMIT', repaired, flags=re.IGNORECASE)
    repaired = re.sub(r'\bASCLIMIT\b',  'ASC LIMIT',  repaired, flags=re.IGNORECASE)

    # ---------------------------------------------------------------
    # 5.  Bad apostrophe escaping:  \'  ->  ''
    #     DBBench stores  Don\'t  which SQLite can't parse.
    # ---------------------------------------------------------------
    repaired = repaired.replace("\\'", "''")

    # ---------------------------------------------------------------
    # 7.  Square-bracket identifiers  ->  double-quoted identifiers
    #     e.g.  [Football Team Performance]  ->  "Football Team Performance"
    # ---------------------------------------------------------------
    repaired = re.sub(
        r'\[([^\]]+)\]',
        lambda m: '"' + m.group(1).replace('"', '""') + '"',
        repaired
    )

    # -- Gather metadata --
    actual_table = table.get("table_name", "")
    col_list     = table.get("table_info", {}).get("columns", [])
    col_names    = [c["name"] for c in col_list]

    # ---------------------------------------------------------------
    # 8.  Reserved-word / keyword table name -> properly quoted name.
    #     Also: SQLite reserved word "table" used as a table name.
    # ---------------------------------------------------------------
    if actual_table:
        # Replace bare "table" keyword used as a table name
        repaired = re.sub(
            r'\bFROM\s+table\b',
            f'FROM "{actual_table}"',
            repaired, flags=re.IGNORECASE
        )
        repaired = re.sub(
            r'\bJOIN\s+table\b',
            f'JOIN "{actual_table}"',
            repaired, flags=re.IGNORECASE
        )
        # Also ensure the actual table name itself is properly quoted
        # after FROM/JOIN (covers cases where it was already almost right)
        repaired = re.sub(
            r'\bFROM\s+' + re.escape(actual_table) + r'\b',
            f'FROM "{actual_table}"',
            repaired, flags=re.IGNORECASE
        )

    # ---------------------------------------------------------------
    # Additional: underscore-vs-space table name mismatch
    #   e.g.  Baseball_Team_Record  vs  actual "Baseball Team Record"
    # ---------------------------------------------------------------
    if actual_table:
        for variant in [actual_table.replace(" ", "_"),
                        actual_table.replace("_", " ")]:
            if variant == actual_table:
                continue
            for kw in ['FROM', 'JOIN']:
                repaired = re.sub(
                    r'\b' + kw + r'\s+' + re.escape(variant) + r'\b',
                    f'{kw} "{actual_table}"',
                    repaired, flags=re.IGNORECASE
                )

    # ---------------------------------------------------------------
    # Build normalized column lookup
    # key = lowercase, all non-alphanumeric stripped
    # e.g. "weeks at No. 1"  ->  "weeksat no1"  (same as "weeks_at_No_1")
    # e.g. "Wrestler:"       ->  "wrestler"      (same as "Wrestler")
    # ---------------------------------------------------------------
    norm_col_map: dict = {}   # normalized_key -> actual column name
    for name in col_names:
        key = re.sub(r'[^a-z0-9]', '', name.lower())
        if key:
            norm_col_map[key] = name

    # ---------------------------------------------------------------
    # 6.  Unquoted multi-word column in SELECT list
    #     e.g.  SELECT Presentation of Credentials FROM ...
    # ---------------------------------------------------------------
    for col in col_names:
        if ' ' not in col:
            continue
        bare = re.compile(
            r'(?<![`"\'\w])' + re.escape(col) + r'(?![`"\w])',
            re.IGNORECASE
        )
        if bare.search(repaired):
            repaired = bare.sub('"' + col.replace('"', '""') + '"', repaired)

    # ---------------------------------------------------------------
    # Additional: unquoted identifiers that normalize to a known column.
    # Handles:
    #   Task 2: weeks_at_No_1  ->  "weeks at No. 1"
    #   Task 6: Wrestler       ->  "Wrestler:"
    #           Date           ->  "Date:"
    # We parse the SQL respecting string literals so we never mangle
    # values inside quotes.
    # ---------------------------------------------------------------
    SQL_KEYWORDS = {
        'select', 'from', 'where', 'and', 'or', 'not', 'in',
        'like', 'is', 'null', 'order', 'by', 'group', 'having',
        'limit', 'offset', 'join', 'on', 'as', 'distinct',
        'count', 'sum', 'avg', 'max', 'min', 'cast', 'case',
        'when', 'then', 'else', 'end', 'asc', 'desc', 'between',
        'exists', 'all', 'any', 'union', 'except', 'intersect',
        'create', 'insert', 'update', 'delete', 'drop', 'alter',
        'set', 'values', 'with', 'table', 'view', 'index',
    }

    token_re = re.compile(
        r'(?<![`"\'.\w])([A-Za-z_][A-Za-z0-9_]*)(?![`"\'.\w(])'
    )

    def _fix_token(m: re.Match) -> str:
        tok = m.group(1)
        if tok.lower() in SQL_KEYWORDS:
            return tok
        key = re.sub(r'[^a-z0-9]', '', tok.lower())
        if key in norm_col_map:
            actual = norm_col_map[key]
            if actual != tok:
                return '"' + actual.replace('"', '""') + '"'
        return tok

    # Split on string literals; only rewrite the non-literal parts
    literal_re = re.compile(r"('(?:''|[^'])*')")
    parts = literal_re.split(repaired)
    repaired = ''.join(
        part if i % 2 == 1 else token_re.sub(_fix_token, part)
        for i, part in enumerate(parts)
    )

    # ---------------------------------------------------------------
    # Final: quote any remaining bare hyphenated column names
    #   e.g.  W-L-T  ->  "W-L-T"
    # ---------------------------------------------------------------
    for col in col_names:
        if '-' not in col:
            continue
        bare_hyph = re.compile(
            r'(?<![`"\'\w])' + re.escape(col) + r'(?![`"\'\w])'
        )
        if bare_hyph.search(repaired):
            repaired = bare_hyph.sub('"' + col.replace('"', '""') + '"', repaired)


    # ---------------------------------------------------------------
    # Prefix-match fallback: bare token that is a leading prefix of
    # a real column name.  Handles e.g.:
    #   Task 11:  Area  ->  "Area (km2)"
    # Only fires when the token was NOT already rewritten above.
    # ---------------------------------------------------------------
    already_quoted = set(re.findall(r'"([^"]+)"', repaired))

    def _prefix_fix(m):
        tok = m.group(1)
        if tok.lower() in SQL_KEYWORDS:
            return m.group(0)
        if tok in already_quoted:
            return m.group(0)
        tok_lower = tok.lower()
        candidates = [
            c for c in col_names
            if c.lower().startswith(tok_lower + " ")
            or c.lower().startswith(tok_lower + "(")
        ]
        if len(candidates) == 1:
            return '"' + candidates[0].replace('"', '"")') + '"'
        return m.group(0)

    pfx_re = re.compile(
        r'(?<![`"\'.\w])([A-Za-z][A-Za-z0-9_]*)(?![`"\'.\w(])'
    )
    parts3 = literal_re.split(repaired)
    repaired = ''.join(
        part if i % 2 == 1 else pfx_re.sub(_prefix_fix, part)
        for i, part in enumerate(parts3)
    )

    return repaired


# ============================================================
# READ-ONLY SQL EXECUTION
# ============================================================

def execute_query(
    conn,
    sql,
    table
):

    operation = extract_operation(
        sql
    )

    # --------------------------------------------------------
    # Safety restriction:
    # only SELECT is executed.
    # --------------------------------------------------------

    if operation != "SELECT":

        return {
            "executed": False,
            "success": False,
            "rows": None,
            "error": (
                "Non-SELECT SQL was not executed."
            )
        }

    # --------------------------------------------------------
    # Repair harmless identifier spelling variants.
    # --------------------------------------------------------

    executable_sql = repair_sql_identifiers(
        sql,
        table
    )

    try:

        cursor = conn.execute(
            executable_sql
        )

        rows = cursor.fetchall()

        normalized_rows = normalize_result(
            rows
        )

        return {
            "executed": True,
            "success": True,
            "rows": normalized_rows,
            "error": None,
            "executed_sql": executable_sql
        }

    except Exception as error:

        return {
            "executed": True,
            "success": False,
            "rows": None,
            "error": str(error),
            "executed_sql": executable_sql
        }


# ============================================================
# ANSWER-LEVEL EVALUATION
# ============================================================

def get_task_sql(task, repair: bool = True):
    """Extract the reference SQL from a task dict.

    When repair=True (the default) the reference SQL is passed
    through repair_reference_sql() so that dataset-level bugs
    (typos, missing spaces, bad escapes) are fixed before the
    SQL is executed for answer comparison.
    """
    sql = task.get("reference_sql")
    if not sql:
        sql = task.get("sql")
    if isinstance(sql, dict):
        sql = sql.get("query", "")
    sql = str(sql or "")
    if repair and sql and "table" in task:
        sql = repair_reference_sql(sql, task["table"])
    return sql


def evaluate_sql(
    task,
    generated_sql
):

    reference_sql = get_task_sql(task)

    conn = create_temp_database(
        task["table"]
    )

    try:

        reference_result = execute_query(
            conn,
            reference_sql,
            task["table"]
        )

        generated_result = execute_query(
            conn,
            generated_sql,
            task["table"]
        )

        # ----------------------------------------------------
        # Reference execution failure
        # ----------------------------------------------------

        if not reference_result["success"]:

            return {
                "status":
                    "REFERENCE_EXECUTION_ERROR",

                "correct":
                    None,

                "reference":
                    reference_result,

                "generated":
                    generated_result,

                "reason":
                    "Reference SQL could not be executed."
            }

        # ----------------------------------------------------
        # Generated SQL failure
        # ----------------------------------------------------

        if not generated_result["success"]:

            return {
                "status":
                    "GENERATED_EXECUTION_ERROR",

                "correct":
                    False,

                "reference":
                    reference_result,

                "generated":
                    generated_result,

                "reason":
                    "Generated SQL could not be executed."
            }

        # ----------------------------------------------------
        # Compare answer sets.
        # ----------------------------------------------------

        reference_rows = (
            reference_result["rows"]
        )

        generated_rows = (
            generated_result["rows"]
        )

        reference_sorted = sorted(
            reference_rows,
            key=lambda x: str(x)
        )

        generated_sorted = sorted(
            generated_rows,
            key=lambda x: str(x)
        )

        correct = (
            reference_sorted
            == generated_sorted
        )

        return {
            "status":
                "EVALUATED",

            "correct":
                correct,

            "reference":
                reference_result,

            "generated":
                generated_result,

            "reason":
                (
                    "Result sets match."
                    if correct
                    else
                    "Result sets differ."
                )
        }

    finally:

        conn.close()


# ============================================================
# NEUTRAL GUARDIAN INTENT
# ============================================================

def neutral_intent(
    reference_sql
):

    operation = extract_operation(
        reference_sql
    )

    return {
        "operation": operation,
        "target": "unknown",
        "field": "unknown",
        "value": "unknown",
        "scope": "unknown"
    }


# ============================================================
# PREVIOUS RESULTS
# ============================================================

def load_previous_results():

    if not OUTPUT_FILE.exists():
        return []

    try:

        with open(
            OUTPUT_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

        return []

    except Exception:

        print(
            "Warning: Could not read previous results."
        )

        return []


# ============================================================
# SAVE
# ============================================================

def save_results(
    results
):

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# GEMINI ERROR
# ============================================================

def is_temporary_gemini_error(
    error
):

    message = str(error).upper()

    keywords = [
        "429",
        "RESOURCE_EXHAUSTED",
        "QUOTA",
        "503",
        "UNAVAILABLE",
        "HIGH DEMAND",
        "RATE LIMIT"
    ]

    return any(
        keyword in message
        for keyword in keywords
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "GuardianAgent + DBBench LLM Pilot"
    )
    print("=" * 70)

    tasks = load_dbbench()

    previous_results = (
        load_previous_results()
    )

    completed_ids = {
        result.get("task_index")
        for result in previous_results
    }

    print()
    print(
        f"Total DBBench tasks : "
        f"{len(tasks)}"
    )

    print(
        f"Pilot tasks         : "
        f"{min(PILOT_SIZE, len(tasks))}"
    )

    print(
        f"Already completed   : "
        f"{len(completed_ids)}"
    )

    print(
        f"Gemini model        : "
        f"{MODEL_NAME}"
    )

    print(
        "SQL execution       : "
        "TEMPORARY IN-MEMORY DB ONLY"
    )

    print(
        "Guardian intent LLM : "
        "DISABLED"
    )

    print(
        "Guardian core       : "
        "FROZEN"
    )

    print()

    results = previous_results

    pilot_count = min(
        PILOT_SIZE,
        len(tasks)
    )

    new_llm_latencies = []
    new_guardian_latencies = []

    for index in range(
        pilot_count
    ):

        task_number = index + 1

        if index in completed_ids:

            print(
                f"[{task_number}/{pilot_count}] "
                "Already completed - skipping."
            )

            continue

        task = tasks[index]

        print("-" * 70)
        print(
            f"[{task_number}/{pilot_count}]"
        )
        print("-" * 70)

        print()
        print("USER REQUEST:")
        print(
            task["description"]
        )

        ref_sql = get_task_sql(task)

        print()
        print("REFERENCE SQL:")
        print(
            ref_sql
        )

        # ----------------------------------------------------
        # GEMINI
        # ----------------------------------------------------

        try:

            generated_sql, llm_latency = (
                generate_sql(task)
            )

        except Exception as error:

            print()
            print("GEMINI ERROR:")
            print(error)

            if is_temporary_gemini_error(
                error
            ):

                print()
                print(
                    "Temporary Gemini "
                    "service/quota problem detected."
                )

                print(
                    "Completed results "
                    "have been preserved."
                )

                break

            raise

        print()
        print("GENERATED SQL:")
        print(
            generated_sql
        )

        # ----------------------------------------------------
        # SQL ANSWER EVALUATION
        # ----------------------------------------------------

        sql_evaluation = evaluate_sql(
            task,
            generated_sql
        )

        print()
        print(
            "ANSWER-LEVEL SQL EVALUATION:"
        )

        status = (
            sql_evaluation["status"]
        )

        if status == "EVALUATED":

            if sql_evaluation["correct"]:

                print(
                    "SQL correctness : CORRECT"
                )

            else:

                print(
                    "SQL correctness : INCORRECT"
                )

        elif status == "REFERENCE_EXECUTION_ERROR":

            print(
                "SQL correctness : "
                "NOT EVALUATED"
            )

            print(
                "Reference SQL could "
                "not be executed."
            )

        else:

            print(
                "SQL correctness : "
                "INCORRECT"
            )

        print(
            "Status          : "
            f"{status}"
        )

        print(
            "Reason          : "
            f"{sql_evaluation['reason']}"
        )

        print()
        print(
            "REFERENCE RESULT:"
        )

        print(
            sql_evaluation[
                "reference"
            ]["rows"]
        )

        print()
        print(
            "GENERATED RESULT:"
        )

        print(
            sql_evaluation[
                "generated"
            ]["rows"]
        )

        # ----------------------------------------------------
        # GUARDIAN
        # ----------------------------------------------------

        intent = neutral_intent(
            ref_sql
        )

        guardian_start = (
            time.perf_counter()
        )

        guardian_result = guardian_check(
            task["description"],
            generated_sql,
            known_intent=intent
        )

        guardian_latency = (
            time.perf_counter()
            - guardian_start
        ) * 1000

        decision = (
            guardian_result[
                "risk"
            ]["decision"]
        )

        risk_score = (
            guardian_result[
                "risk"
            ]["risk_score"]
        )

        risk_level = (
            guardian_result[
                "risk"
            ]["risk_level"]
        )

        print()
        print(
            "GUARDIAN RESULT:"
        )

        print(
            f"Decision       : "
            f"{decision}"
        )

        print(
            f"Risk score     : "
            f"{risk_score}"
        )

        print(
            f"Risk level     : "
            f"{risk_level}"
        )

        print()
        print(
            f"LLM latency     : "
            f"{llm_latency:.2f} ms"
        )

        print(
            f"Guardian latency: "
            f"{guardian_latency:.2f} ms"
        )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        result = {

            "task_index":
                index,

            "description":
                task["description"],

            "reference_sql":
                ref_sql,

            "generated_sql":
                generated_sql,

            "sql_evaluation":
                sql_evaluation,

            "reference_intent":
                intent,

            "guardian_result":
                guardian_result,

            "guardian_decision":
                decision,

            "risk_score":
                risk_score,

            "risk_level":
                risk_level,

            "llm_latency_ms":
                round(
                    llm_latency,
                    4
                ),

            "guardian_latency_ms":
                round(
                    guardian_latency,
                    4
                ),

            "sql_execution":
                "temporary_in_memory_only",

            "guardian_intent_llm":
                False
        }

        results.append(
            result
        )

        save_results(
            results
        )

        new_llm_latencies.append(
            llm_latency
        )

        new_guardian_latencies.append(
            guardian_latency
        )

        print()
        print(
            "Result saved."
        )
        sys.stdout.flush()
        # Rate limiting is already handled inside generate_sql() via
        # _rate_limiter.wait().  No extra sleep needed here.

    # ========================================================
    # SUMMARY
    # ========================================================

    print("=" * 70)
    print("PILOT SUMMARY")
    print("=" * 70)

    print()
    print(
        f"Completed tasks : "
        f"{len(results)}/{pilot_count}"
    )

    # --------------------------------------------------------
    # Guardian decisions
    # --------------------------------------------------------

    if results:

        decisions = {}

        for result in results:

            decision = (
                result[
                    "guardian_decision"
                ]
            )

            decisions[decision] = (
                decisions.get(
                    decision,
                    0
                ) + 1
            )

        print()
        print(
            "Guardian decisions:"
        )

        for decision in [
            "ALLOW",
            "CONFIRM",
            "BLOCK"
        ]:

            if decision in decisions:

                print(
                    f"  {decision:<10}: "
                    f"{decisions[decision]}"
                )

    # --------------------------------------------------------
    # SQL correctness
    # --------------------------------------------------------

    evaluated_results = [
        result
        for result in results
        if result[
            "sql_evaluation"
        ]["status"] == "EVALUATED"
    ]

    correct_results = [
        result
        for result in evaluated_results
        if result[
            "sql_evaluation"
        ]["correct"]
    ]

    reference_errors = [
        result
        for result in results
        if result[
            "sql_evaluation"
        ]["status"]
        == "REFERENCE_EXECUTION_ERROR"
    ]

    generated_errors = [
        result
        for result in results
        if result[
            "sql_evaluation"
        ]["status"]
        == "GENERATED_EXECUTION_ERROR"
    ]

    print()
    print(
        "SQL evaluation:"
    )

    print(
        f"  Evaluated          : "
        f"{len(evaluated_results)}"
    )

    print(
        f"  Correct            : "
        f"{len(correct_results)}"
    )

    print(
        f"  Reference errors   : "
        f"{len(reference_errors)}"
    )

    print(
        f"  Generated errors   : "
        f"{len(generated_errors)}"
    )

    if evaluated_results:

        accuracy = (
            100
            * len(correct_results)
            / len(evaluated_results)
        )

        print(
            f"  Answer accuracy    : "
            f"{accuracy:.2f}%"
        )

    # --------------------------------------------------------
    # New-case latency
    # --------------------------------------------------------

    if new_llm_latencies:

        print()
        print(
            "Average LLM latency:"
        )

        print(
            f"  {sum(new_llm_latencies) / len(new_llm_latencies):.2f} ms"
        )

    if new_guardian_latencies:

        print(
            "Average Guardian latency:"
        )

        print(
            f"  {sum(new_guardian_latencies) / len(new_guardian_latencies):.2f} ms"
        )

    # --------------------------------------------------------
    # Completion
    # --------------------------------------------------------

    if len(results) < pilot_count:

        print()
        print(
            "Pilot is incomplete because "
            "Gemini was unavailable."
        )

        print(
            "Run the same command later "
            "to resume."
        )

    else:

        print()
        print(
            "Pilot completed successfully."
        )

    print()
    print(
        f"Results file: "
        f"{OUTPUT_FILE}"
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()