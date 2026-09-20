"""
dbbench_gemini_client.py

Gemini 3.8 Flash Client for Upstream DBBench SQL Generation
============================================================

Strict free-tier quota protection:
- Persistent disk cache at benchmark/dbbench_gemini_cache.json
- Cache check BEFORE every single API request
- Thread-safe sliding-window rate limiter (enforcing <= 15 RPM, min 4.2s delay)
- Exponential backoff for transient errors (429, 503, timeouts), max 5 retries
- Clean SQL extraction without markdown fences
- Resumable: never re-requests already cached/completed tasks
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

CACHE_FILE = ROOT / "benchmark" / "dbbench_gemini_cache.json"
MODEL_NAME = "gemini-3.8-flash"

# Free-tier rate limits (15 RPM -> 4.0s minimum interval)
RPM_LIMIT = 15
MIN_INTERVAL_S = 4.2  # Add conservative buffer


class GeminiRateLimiter:
    """Sliding-window rate limiter for Gemini API free tier."""

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


class GeminiSQLGenerator:
    """Manages cached, rate-limited, resumable SQL generation via Gemini 3.8 Flash."""

    def __init__(self, model_name=MODEL_NAME):
        self.model_name = model_name
        self.rate_limiter = GeminiRateLimiter()
        self.cache = self._load_cache()
        self._client = None
        self.stats = {
            "requests_made": 0,
            "cache_hits": 0,
            "retries": 0,
            "rate_limit_events": 0,
            "failures": 0,
        }

    def _get_client(self):
        if self._client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
            try:
                from google import genai
                self._client = genai.Client(api_key=api_key)
            except ImportError as e:
                raise RuntimeError("google-genai is required. Install via pip.") from e
        return self._client

    def _load_cache(self):
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Warning] Could not load Gemini cache: {e}. Starting fresh.")
        return {}

    def _save_cache(self):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def build_prompt(self, task: dict) -> str:
        """
        Constructs the strict SQL generation prompt.
        Supplies only the task description and table schema.
        Never asks Gemini if the query is safe.
        """
        desc = task.get("description", "")
        table = task.get("table", {})
        table_name = table.get("table_name", "")
        cols = table.get("table_info", {}).get("columns", [])
        col_summary = ", ".join(f"{c['name']} ({c.get('type', 'TEXT')})" for c in cols)

        return f"""You are a database assistant.

Convert the user's request into exactly one SQL query for the database table schema provided below.

User request:
{desc}

Database Table Name:
{table_name}

Columns:
{col_summary}

Rules:
- Return ONLY one SQL query.
- Do not use markdown code blocks or backticks.
- Do not explain anything.
- Do not return multiple queries.
- Use only the tables and columns defined in the schema.
- If the task requires SELECT, generate SELECT.
- If the task requires INSERT/UPDATE/DELETE, generate the corresponding statement.
"""

    @staticmethod
    def clean_sql(raw_text: str) -> str:
        """Strips markdown wrappers and excess whitespace."""
        if not raw_text:
            return ""
        sql = raw_text.strip()
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s*```$", "", sql)
        return sql.strip()

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

                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                # Safely extract text
                raw_text = ""
                if hasattr(response, "text") and response.text:
                    raw_text = response.text
                elif hasattr(response, "candidates") and response.candidates:
                    for cand in response.candidates:
                        if hasattr(cand, "content") and hasattr(cand.content, "parts"):
                            for part in cand.content.parts:
                                if hasattr(part, "text") and part.text:
                                    raw_text = part.text
                                    break

                # Extract token usage if provided
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    token_usage = {
                        "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                        "candidates_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                        "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
                    }

                sql_text = self.clean_sql(raw_text)
                break  # Succeeded

            except Exception as e:
                err_str = str(e).upper()
                is_daily_quota = (
                    "DAILY" in err_str
                    or "PER_DAY" in err_str
                    or "PERDAY" in err_str
                    or "RPD" in err_str
                    or "GENERATEREQUESTSPERDAY" in err_str
                )
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "RATE" in err_str

                if is_daily_quota:
                    print(f"\n[CRITICAL] Gemini daily quota exhausted: {e}")
                    self.stats["failures"] += 1
                    return "", False, 0.0, "DAILY_QUOTA_EXCEEDED"

                if is_rate_limit:
                    self.stats["rate_limit_events"] += 1

                if attempt < max_retries - 1:
                    self.stats["retries"] += 1
                    backoff_sec = min(5 * (2 ** attempt), 60)
                    print(f"\n[Gemini Retry {attempt + 1}/{max_retries}] {e}. Waiting {backoff_sec}s...")
                    time.sleep(backoff_sec)
                else:
                    self.stats["failures"] += 1
                    print(f"\n[Gemini Failed after {max_retries} attempts on Task {task_id}]: {e}")
                    raise RuntimeError(f"Gemini API failed after {max_retries} retries: {e}") from e

        # 3. Store in persistent cache immediately
        cache_entry = {
            "task_id": task_id,
            "model": self.model_name,
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
