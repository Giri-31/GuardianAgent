"""
dbbench_groq_client.py

Groq Client for Upstream DBBench SQL Generation
===============================================
Model: openai/gpt-oss-120b
Reasoning Effort: medium

Features:
- Reads GROQ_API_KEY from environment variable (never hardcoded, never logged)
- Persistent disk cache at benchmark/dbbench_groq_cache.json
- Cache check BEFORE every single API request
- Rate limiting and exponential backoff (max 5 retries) for transient errors (429, 503, timeouts)
- Minimal extraction from markdown fences without altering SQL semantics
- Resumable: never re-requests already cached tasks
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE_FILE = ROOT / "benchmark" / "dbbench_groq_cache.json"
MODEL_NAME = "openai/gpt-oss-120b"
REASONING_EFFORT = "medium"
MIN_INTERVAL_S = 1.0


class GroqRateLimiter:
    """Sliding-window rate limiter for Groq API."""

    def __init__(self, min_interval=MIN_INTERVAL_S):
        self.min_interval = min_interval
        self.last_call_time = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_call_time
            if elapsed < self.min_interval:
                sleep_dur = self.min_interval - elapsed
                time.sleep(sleep_dur)
            self.last_call_time = time.monotonic()


class GroqSQLGenerator:
    """Manages cached, rate-limited, resumable SQL generation via Groq GPT-OSS-120B."""

    def __init__(self, model_name=MODEL_NAME, reasoning_effort=REASONING_EFFORT):
        self.model_name = model_name
        self.reasoning_effort = reasoning_effort
        self.rate_limiter = GroqRateLimiter()
        self.cache = self._load_cache()
        self.stats = {
            "requests_made": 0,
            "cache_hits": 0,
            "retries": 0,
            "rate_limit_events": 0,
            "failures": 0,
        }

    def _get_api_key(self) -> str:
        key = os.getenv("GROQ_API_KEY")
        if not key or not key.strip():
            env_file = ROOT / ".env"
            if env_file.exists():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("GROQ_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            os.environ["GROQ_API_KEY"] = val
                            key = val
                            break
        if not key or not key.strip():
            raise RuntimeError(
                "CRITICAL ERROR: GROQ_API_KEY environment variable is not set. "
                "Please set GROQ_API_KEY in your environment before running this script."
            )
        return key.strip()

    def _get_client(self):
        from groq import Groq
        api_key = self._get_api_key()
        return Groq(api_key=api_key)

    def _load_cache(self) -> dict:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Warning] Failed to load Groq cache from {CACHE_FILE}: {e}")
        return {}

    def _save_cache(self):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = CACHE_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)
        temp_file.replace(CACHE_FILE)

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def build_prompt(self, task: dict) -> str:
        """Constructs prompt providing database schema, sample data, and general SQL guidelines."""
        table = task.get("table", {})
        table_name = table.get("table_name", "data_table")
        table_info = table.get("table_info", {})
        columns = table_info.get("columns", [])

        col_lines = []
        for col in columns:
            cname = col.get("name", "")
            ctype = col.get("type", "TEXT")
            col_lines.append(f'  - "{cname}" ({ctype})')
        cols_str = "\n".join(col_lines)

        # Show ALL rows so the model can always see every existing entity
        all_rows = table_info.get("rows", [])
        rows_str = ""
        if all_rows:
            rows_str = f"\nAll existing table rows ({len(all_rows)} total):\n"
            for r in all_rows:
                rows_str += f"  {r}\n"

        instruction = task.get("description", "")

        prompt = (
            f"You are a precise SQLite SQL expert.\n\n"
            f'Table: "{table_name}"\n'
            f"Columns:\n{cols_str}\n"
            f"{rows_str}\n"
            f"Instruction: {instruction}\n\n"
            f"Requirements:\n"
            f"1. Generate a single valid SQLite SQL query to satisfy the instruction.\n"
            f'2. Quote table and column names with double quotes when they contain spaces (e.g. "{table_name}").\n'
            f"3. Operation semantics — CRITICAL: First scan the table rows shown above. "
            f"If you can find a row that matches the entity or subject described in the instruction, "
            f"you MUST use UPDATE ... SET ... WHERE ... to modify that row. "
            f"Only use INSERT when you are certain no matching row exists in the table. "
            f"Choosing INSERT when the entity already exists will produce a duplicate row, which is wrong.\n"
            f"4. Value formatting: Copy string values exactly as they appear in the existing rows "
            f"(preserve commas in numbers like '62,129', special dashes like \u2013, "
            f"spaces around punctuation, and any special characters).\n"
            f"5. Column projection for SELECT: Select ONLY the specific column(s) the instruction asks for. "
            f"When asked 'which [entity] has the highest/lowest [metric]', return the entity name/identifier column. "
            f"When asked to 'name the [metric value]' or report a statistic, return the metric/value column. "
            f"Never use SELECT * unless all columns are explicitly needed.\n"
            f"6. Return ONLY the raw SQL query. Do not include markdown code fences, comments, or explanations."
        )
        return prompt


    def clean_sql(self, raw_sql: str) -> str:
        """Minimal extraction of SQL from markdown fences without altering SQL semantics."""
        text = raw_sql.strip()
        # Remove ```sql ... ``` or ``` ... ```
        pattern = r"^```(?:sql)?\s*(.*?)\s*```$"
        match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
        return text

    def generate_sql_for_task(self, task: dict, force_refresh=False):
        """
        Generates or retrieves cached SQL for a single DBBench task.
        Returns: (sql, is_cached, latency_ms, status)
        """
        task_id = str(task["case_id"])
        prompt = self.build_prompt(task)
        input_hash = self._compute_hash(task.get("description", ""))
        prompt_hash = self._compute_hash(prompt)
        cache_key = f"task_{task_id}_{input_hash[:12]}_{prompt_hash[:12]}"

        # 1. Check persistent cache first
        if not force_refresh and cache_key in self.cache:
            entry = self.cache[cache_key]
            self.stats["cache_hits"] += 1
            return entry["generated_sql"], True, entry.get("latency_ms", 0.0), "CACHED"

        # 2. Make rate-limited API call
        client = self._get_client()
        max_retries = 5
        sql_text = ""
        latency_ms = 0.0
        token_usage = {}

        for attempt in range(max_retries):
            try:
                self.rate_limiter.wait()
                start_time = time.perf_counter()
                self.stats["requests_made"] += 1

                # Include reasoning_effort for models that support it
                try:
                    response = client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        reasoning_effort=self.reasoning_effort,
                    )
                except Exception as param_err:
                    if "reasoning_effort" in str(param_err).lower():
                        # Fallback if reasoning_effort is unsupported by this specific model endpoint
                        response = client.chat.completions.create(
                            model=self.model_name,
                            messages=[{"role": "user", "content": prompt}],
                        )
                    else:
                        raise param_err

                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                raw_text = response.choices[0].message.content or ""
                if hasattr(response, "usage") and response.usage:
                    token_usage = {
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                        "total_tokens": getattr(response.usage, "total_tokens", 0),
                    }

                sql_text = self.clean_sql(raw_text)
                break  # Success

            except Exception as e:
                err_str = str(e).upper()
                is_rate_limit = "429" in err_str or "RATE_LIMIT" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_daily_quota = (
                    "DAILY" in err_str
                    or "PER_DAY" in err_str
                    or "PERDAY" in err_str
                    or "RPD" in err_str
                )

                if is_daily_quota:
                    print(f"\n[CRITICAL] Groq daily quota exhausted: {e}")
                    self.stats["failures"] += 1
                    return "", False, 0.0, "DAILY_QUOTA_EXCEEDED"

                if is_rate_limit:
                    self.stats["rate_limit_events"] += 1

                if attempt < max_retries - 1:
                    self.stats["retries"] += 1
                    backoff_sec = min(3 * (2 ** attempt), 30)
                    print(f"\n[Groq Retry {attempt + 1}/{max_retries}] {e}. Waiting {backoff_sec}s...")
                    time.sleep(backoff_sec)
                else:
                    self.stats["failures"] += 1
                    print(f"\n[Groq Failed after {max_retries} attempts on Task {task_id}]: {e}")
                    raise RuntimeError(f"Groq API failed after {max_retries} retries: {e}") from e

        # 3. Store in persistent cache immediately
        cache_entry = {
            "task_id": task_id,
            "model": self.model_name,
            "reasoning_effort": self.reasoning_effort,
            "prompt_hash": prompt_hash,
            "input_hash": input_hash,
            "generated_sql": sql_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "api_status": "SUCCESS",
            "token_usage": token_usage,
            "latency_ms": latency_ms,
        }
        self.cache[cache_key] = cache_entry
        self._save_cache()

        return sql_text, False, latency_ms, "SUCCESS"
