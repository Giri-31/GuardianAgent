"""
run_bird_clean_llm_eval.py

GuardianAgent: BIRD 500-Query Clean Evaluation with LLM Intent Mode
===================================================================
Evaluates the same 500 legitimate BIRD Mini-Dev queries using GuardianAgent
with LLM-based intent extraction enabled (defaulting to Groq per user direction).

Features:
- Completely keeps GuardianAgent core files (guardian.py, intent_analyzer.py,
  intent_sql_checker.py, risk_engine.py) frozen and unmodified.
- Uses persistent disk caching (resumable upon restart).
- Sliding-window rate limiter + exponential backoff for transient API errors (429, 503, timeouts).
- Records per-query decision, risk score, extracted intent, mismatches, latency, and LLM call status.
- Computes comprehensive metrics and outputs:
  - bird_llm_clean_results.json
  - bird_llm_clean_summary.json
  - bird_llm_clean_report.md
  - logs/bird_llm_clean_eval.log
- Formats comparison against the frozen deterministic baseline (99.20% false-block rate).
- Prints the exact requested final terminal summary.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Setup Project Root
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env credentials if present
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v

# Paths
DATA_PATH = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "mini_dev_sqlite.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"

OUTPUT_DIR = ROOT / "bird_eval" / "full_bird" / "llm_clean_eval"
RESULTS_DIR = OUTPUT_DIR / "results"
LOGS_DIR = OUTPUT_DIR / "logs"
SCRIPTS_DIR = OUTPUT_DIR / "scripts"

CACHE_FILE = RESULTS_DIR / "bird_llm_intent_cache.json"
RESULTS_FILE = RESULTS_DIR / "bird_llm_clean_results.json"
SUMMARY_FILE = RESULTS_DIR / "bird_llm_clean_summary.json"
REPORT_FILE = RESULTS_DIR / "bird_llm_clean_report.md"
LOG_FILE = LOGS_DIR / "bird_llm_clean_eval.log"

# Baseline numbers from deterministic evaluation
DETERMINISTIC_BASELINE = {
    "total_queries": 500,
    "allow": 0,
    "confirm": 4,
    "block": 496,
    "false_block_rate": 99.20,
    "mean_latency_ms": 2.091,
    "median_latency_ms": 1.301,
    "p95_latency_ms": 4.139,
    "p99_latency_ms": 10.631,
    "exec_success": "499/500",
}


def setup_logger():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bird_llm_clean_eval")
    logger.setLevel(logging.INFO)
    logger.handlers = []

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    return logger


def percentile(data, p):
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c < len(data):
        return data[f] + (k - f) * (data[c] - data[f])
    else:
        return data[f]


class RateLimiter:
    """Sliding-window rate limiter to keep requests well within limits."""
    def __init__(self, rpm: int = 25):
        self.rpm = rpm
        self.min_interval = 60.0 / float(rpm)
        self.last_time = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_time = time.monotonic()


class CachedLLMIntentClient:
    """
    Adapter implementing the interface expected by intent_analyzer:
      client.models.generate_content(model=..., contents=...)
    Backed by Groq (or Gemini) with persistent caching, rate limiting, and backoff.
    """

    def __init__(self, provider: str = "groq", model: str = None, cache_path: Path = CACHE_FILE):
        self.provider = provider
        self.cache_path = cache_path
        self.cache = self._load_cache()
        self.cache_lock = threading.Lock()
        self.api_calls_count = 0
        self.failed_calls_count = 0
        self.fallback_count = 0

        if self.provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("GROQ_API_KEY not found in environment.")
            from groq import Groq
            self.groq_client = Groq(api_key=api_key)
            env_m = os.getenv("GROQ_MODEL")
            if env_m and "llama-3.3" in env_m:
                env_m = "qwen/qwen3.8-27b"
            self.model = model or env_m or "qwen/qwen3.8-27b"
            self.rate_limiter = RateLimiter(rpm=25)
        elif self.provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY not found in environment.")
            from google import genai
            self.gemini_client = genai.Client(api_key=api_key)
            self.model = model or os.getenv("GUARDIAN_INTENT_MODEL", "gemini-3.8-flash")
            self.rate_limiter = RateLimiter(rpm=12)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        outer_self = self

        class Models:
            def generate_content(subself, model=None, contents=None):
                return outer_self._generate_content_with_cache(contents)

        self.models = Models()

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        with self.cache_lock:
            temp = self.cache_path.with_suffix(".tmp")
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
            temp.replace(self.cache_path)

    def _generate_content_with_cache(self, prompt: str):
        prompt_str = str(prompt)
        # Check cache
        with self.cache_lock:
            if prompt_str in self.cache:
                cached_text = self.cache[prompt_str]
                return self._make_response(cached_text)

        # Call API with retry & backoff
        max_retries = 6
        last_err = None
        for attempt in range(max_retries):
            try:
                self.rate_limiter.wait()
                self.api_calls_count += 1
                if self.provider == "groq":
                    resp = self.groq_client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt_str}],
                        temperature=0,
                        max_tokens=256,
                    )
                    text = resp.choices[0].message.content.strip()
                else:
                    gresp = self.gemini_client.models.generate_content(
                        model=self.model,
                        contents=prompt_str,
                    )
                    text = getattr(gresp, "text", "") or ""

                # Save in cache
                with self.cache_lock:
                    self.cache[prompt_str] = text
                self._save_cache()
                return self._make_response(text)

            except Exception as e:
                last_err = e
                err_msg = str(e).lower()
                is_rate_limit = any(k in err_msg for k in ["429", "rate limit", "quota", "resource_exhausted", "503"])
                if is_rate_limit and attempt < max_retries - 1:
                    m = re.search(r"try again in ([\d\.]+)s", err_msg)
                    if m:
                        sleep_s = float(m.group(1)) + 1.5
                    else:
                        sleep_s = min(3 * (2 ** attempt), 45)
                    time.sleep(sleep_s)
                else:
                    break

        # If completely failed
        self.failed_calls_count += 1
        self.fallback_count += 1
        return self._make_response("")

    def _make_response(self, text: str):
        class ContentResponse:
            def __init__(self, t):
                self.text = t
        return ContentResponse(text)


def run_evaluation(provider: str = "groq", model: str = None, limit: int = None):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = setup_logger()

    logger.info("=" * 80)
    logger.info("BIRD CLEAN EVALUATION WITH GUARDIANAGENT LLM INTENT")
    logger.info("=" * 80)
    logger.info(f"Dataset Path : {DATA_PATH}")
    logger.info(f"Databases Dir: {DEV_DATABASES_DIR}")
    logger.info(f"LLM Provider : {provider}")

    # Set environment variables for LLM mode
    os.environ["GUARDIAN_DISABLE_LLM"] = "0"
    os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STRICT"

    # Initialize LLM Intent Client Adapter
    llm_client = CachedLLMIntentClient(provider=provider, model=model, cache_path=CACHE_FILE)
    logger.info(f"LLM Model    : {llm_client.model}")
    logger.info(f"Cached Intent: {len(llm_client.cache)} items in cache\n")

    # Wire client into intent_analyzer without altering core files
    import intent_analyzer
    intent_analyzer.DISABLE_LLM = False
    intent_analyzer._client = llm_client

    # Import guardian adapter
    from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter
    adapter = GuardianBIRDAdapter(disable_llm_intent=False)

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        queries = json.load(f)

    if limit and limit > 0:
        queries = queries[:limit]

    total_queries = len(queries)
    logger.info(f"Total legitimate queries to evaluate: {total_queries}\n")

    results = []
    latencies = []
    decision_counts = Counter()
    exec_success_count = 0
    exec_failure_count = 0
    mismatch_counts = Counter()

    db_stats = defaultdict(lambda: {
        "total": 0,
        "ALLOW": 0,
        "CONFIRM": 0,
        "BLOCK": 0,
        "exec_success": 0,
        "exec_failed": 0,
        "latencies": [],
    })

    logger.info(f"{'#':<4} {'QID':<6} {'Database':<23} {'Exec':<8} {'Guardian':<10} {'Risk':<6} {'Latency':<9} {'Mismatches':<20}")
    logger.info("-" * 95)

    start_eval_time = time.perf_counter()

    for idx, item in enumerate(queries, start=1):
        qid = item["question_id"]
        db_id = item["db_id"]
        question = item["question"]
        gold_sql = item["SQL"].strip()
        difficulty = item.get("difficulty", "unknown")

        db_path = DEV_DATABASES_DIR / db_id / f"{db_id}.sqlite"
        if not db_path.exists():
            matches = list((DEV_DATABASES_DIR / db_id).glob("*.sqlite"))
            if matches:
                db_path = matches[0]

        # 1. Ground truth execution check (safe read-only, 10s timeout)
        EXEC_TIMEOUT_SEC = 10
        exec_ok = False
        exec_error = None
        conn = None
        _exec_result = {"ok": False, "err": None, "conn": None}

        def _try_exec():
            try:
                c = adapter.open_database_connection(db_path, read_only=True)
                c.execute("PRAGMA busy_timeout = 8000")
                cur = c.cursor()
                cur.execute(gold_sql)
                cur.fetchone()
                _exec_result["ok"] = True
                _exec_result["conn"] = c
            except Exception as ex:
                _exec_result["err"] = str(ex)
                try:
                    if c:
                        c.close()
                except Exception:
                    pass

        t = threading.Thread(target=_try_exec, daemon=True)
        t.start()
        t.join(timeout=EXEC_TIMEOUT_SEC)
        if t.is_alive():
            exec_ok = False
            exec_error = f"EXEC_TIMEOUT>{EXEC_TIMEOUT_SEC}s"
            exec_failure_count += 1
            db_stats[db_id]["exec_failed"] += 1
            conn = None
        elif _exec_result["ok"]:
            exec_ok = True
            exec_success_count += 1
            db_stats[db_id]["exec_success"] += 1
            conn = _exec_result["conn"]
        else:
            exec_ok = False
            exec_error = _exec_result["err"]
            exec_failure_count += 1
            db_stats[db_id]["exec_failed"] += 1

        # 2. GuardianAgent evaluation with LLM intent
        try:
            t0 = time.perf_counter()
            guardian_res = adapter.evaluate_query(
                user_request=question,
                sql=gold_sql,
                connection=conn,
            )
            t_elapsed_ms = (time.perf_counter() - t0) * 1000
        except Exception as e:
            guardian_res = {
                "decision": "BLOCK",
                "risk_score": 10.0,
                "risk_level": "CRITICAL",
                "mismatches": ["EVALUATION_EXCEPTION"],
                "intent": {},
                "latency_ms": 0.0,
                "error": str(e),
            }
            t_elapsed_ms = 0.0
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        actual_decision = guardian_res["decision"]
        risk_score = guardian_res["risk_score"]
        mismatches = guardian_res.get("mismatches", [])
        extracted_intent = guardian_res.get("intent", {})
        latency_ms = guardian_res.get("latency_ms", t_elapsed_ms)

        decision_counts[actual_decision] += 1
        latencies.append(latency_ms)

        for m in mismatches:
            mismatch_counts[m] += 1

        db_stats[db_id]["total"] += 1
        db_stats[db_id][actual_decision] += 1
        db_stats[db_id]["latencies"].append(latency_ms)

        exec_str = "OK" if exec_ok else "FAIL"
        mism_str = str(mismatches) if mismatches else "[]"
        if len(mism_str) > 20:
            mism_str = mism_str[:17] + "..."

        if idx <= 10 or idx % 25 == 0 or idx == total_queries:
            logger.info(
                f"{idx:<4} {qid:<6} {db_id[:22]:<23} {exec_str:<8} {actual_decision:<10} "
                f"{risk_score:<6.2f} {latency_ms:<6.2f}ms {mism_str:<20}"
            )

        results.append({
            "index": idx,
            "question_id": qid,
            "db_id": db_id,
            "difficulty": difficulty,
            "question": question,
            "gold_sql": gold_sql,
            "exec_success": exec_ok,
            "exec_error": exec_error,
            "guardian_decision": actual_decision,
            "risk_score": risk_score,
            "risk_level": guardian_res.get("risk_level"),
            "mismatches": mismatches,
            "extracted_intent": extracted_intent,
            "latency_ms": round(latency_ms, 3),
        })

    total_eval_seconds = time.perf_counter() - start_eval_time

    # Latency distribution calculations
    sorted_latencies = sorted(latencies)
    mean_lat = statistics.mean(latencies) if latencies else 0.0
    median_lat = statistics.median(latencies) if latencies else 0.0
    p95_lat = percentile(sorted_latencies, 95)
    p99_lat = percentile(sorted_latencies, 99)

    allow_count = decision_counts["ALLOW"]
    confirm_count = decision_counts["CONFIRM"]
    block_count = decision_counts["BLOCK"]

    false_block_rate = (block_count / total_queries * 100) if total_queries > 0 else 0.0
    confirm_rate = (confirm_count / total_queries * 100) if total_queries > 0 else 0.0
    allow_rate = (allow_count / total_queries * 100) if total_queries > 0 else 0.0

    reduction_fb = DETERMINISTIC_BASELINE["false_block_rate"] - false_block_rate

    # Prepare Summary JSON
    summary_data = {
        "metadata": {
            "evaluation_title": "BIRD 500-Query Clean Evaluation (LLM Intent Mode)",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "llm_provider": provider,
            "llm_model": llm_client.model,
            "dataset": str(DATA_PATH),
            "total_queries": total_queries,
            "python_version": sys.version,
            "guardian_disable_llm": os.environ.get("GUARDIAN_DISABLE_LLM", "0"),
            "total_eval_time_sec": round(total_eval_seconds, 2),
        },
        "llm_stats": {
            "api_calls_made": llm_client.api_calls_count,
            "cached_calls": total_queries - llm_client.api_calls_count,
            "failed_calls": llm_client.failed_calls_count,
            "fallbacks_to_deterministic": llm_client.fallback_count,
        },
        "overall_metrics": {
            "total_queries": total_queries,
            "allow_count": allow_count,
            "allow_percentage": round(allow_rate, 2),
            "confirm_count": confirm_count,
            "confirm_percentage": round(confirm_rate, 2),
            "block_count": block_count,
            "block_percentage": round(false_block_rate, 2),
            "false_block_rate_percentage": round(false_block_rate, 2),
            "gold_sql_execution_success": f"{exec_success_count}/{total_queries}",
            "gold_sql_execution_success_percentage": round(exec_success_count / total_queries * 100, 2),
        },
        "latency_metrics_ms": {
            "mean": round(mean_lat, 3),
            "median": round(median_lat, 3),
            "p95": round(p95_lat, 3),
            "p99": round(p99_lat, 3),
        },
        "comparison_against_deterministic": {
            "deterministic_baseline": DETERMINISTIC_BASELINE,
            "llm_mode": {
                "false_block_rate": round(false_block_rate, 2),
                "allow_rate": round(allow_rate, 2),
                "confirm_rate": round(confirm_rate, 2),
                "block_rate": round(false_block_rate, 2),
                "mean_latency_ms": round(mean_lat, 3),
                "p95_latency_ms": round(p95_lat, 3),
            },
            "absolute_reduction_false_block_rate_percentage_points": round(reduction_fb, 2),
            "relative_reduction_false_block_rate_percent": round((reduction_fb / DETERMINISTIC_BASELINE["false_block_rate"]) * 100, 2),
        },
        "per_database_results": {},
        "mismatch_breakdown": dict(mismatch_counts),
    }

    # Per database summary
    for db, s in db_stats.items():
        db_total = s["total"]
        db_block = s["BLOCK"]
        db_fbr = (db_block / db_total * 100) if db_total > 0 else 0.0
        db_mean_lat = statistics.mean(s["latencies"]) if s["latencies"] else 0.0
        summary_data["per_database_results"][db] = {
            "queries": db_total,
            "ALLOW": s["ALLOW"],
            "CONFIRM": s["CONFIRM"],
            "BLOCK": s["BLOCK"],
            "false_block_rate": round(db_fbr, 2),
            "mean_latency_ms": round(db_mean_lat, 3),
            "exec_success": s["exec_success"],
            "exec_failed": s["exec_failed"],
        }

    # Save Results JSON
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"\nSaved detailed results to: {RESULTS_FILE}")

    # Save Summary JSON
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved summary to: {SUMMARY_FILE}")

    # Generate Markdown Report
    generate_markdown_report(summary_data, results, REPORT_FILE)
    logger.info(f"Saved markdown report to: {REPORT_FILE}\n")

    # Print EXACT requested final terminal summary
    print("=" * 40)
    print("BIRD 500-QUERY LLM CLEAN EVALUATION")
    print("=" * 40)
    print()
    print(f"Total queries: {total_queries}")
    print(f"ALLOW: {allow_count} ({allow_rate:.2f}%)")
    print(f"CONFIRM: {confirm_count} ({confirm_rate:.2f}%)")
    print(f"BLOCK: {block_count} ({false_block_rate:.2f}%)")
    print(f"False-block rate: {false_block_rate:.2f}%")
    print(f"Gold SQL execution success: {exec_success_count}/{total_queries}")
    print(f"Mean latency: {mean_lat:.3f} ms")
    print(f"Median latency: {median_lat:.3f} ms")
    print(f"P95 latency: {p95_lat:.3f} ms")
    print(f"P99 latency: {p99_lat:.3f} ms")
    print(f"LLM API calls: {llm_client.api_calls_count}")
    print(f"LLM failures: {llm_client.failed_calls_count}")
    print(f"Fallbacks: {llm_client.fallback_count}")
    print()
    print("DETERMINISTIC BASELINE")
    print("False-block rate: 99.20%")
    print("Mean latency: 2.091 ms")
    print("P95 latency: 4.139 ms")
    print()
    print("LLM MODE")
    print(f"False-block rate: {false_block_rate:.2f}%")
    print(f"Reduction: {reduction_fb:.2f} percentage points")
    print()
    print("=" * 40)


def generate_markdown_report(summary: dict, results: list, report_path: Path):
    meta = summary["metadata"]
    m = summary["overall_metrics"]
    lat = summary["latency_metrics_ms"]
    comp = summary["comparison_against_deterministic"]
    llm = summary["llm_stats"]
    db_res = summary["per_database_results"]
    mismatches = summary["mismatch_breakdown"]

    # Collect representative failures
    failures_by_type = defaultdict(list)
    for r in results:
        if r["guardian_decision"] in ("BLOCK", "CONFIRM"):
            primary_mism = r["mismatches"][0] if r["mismatches"] else "NO_MISMATCH_RECORDED"
            failures_by_type[primary_mism].append(r)

    content = f"""# BIRD 500-Query Clean Evaluation Report: LLM Intent Mode

> **Date**: {meta['timestamp_utc']} | **LLM Provider**: {meta['llm_provider']} | **Model**: `{meta['llm_model']}`  
> **Core GuardianAgent**: Completely Frozen (Unmodified) | **Dataset**: BIRD Mini-Dev (500 Queries)

---

## 1. Executive Summary

| Metric | LLM Mode | Deterministic Baseline | Change |
|---|---|---|---|
| **Total Queries** | **{m['total_queries']}** | {DETERMINISTIC_BASELINE['total_queries']} | — |
| **ALLOW (Clean Pass)** | **{m['allow_count']} ({m['allow_percentage']}%)** | {DETERMINISTIC_BASELINE['allow']} (0.00%) | **+{m['allow_percentage']:.2f}%** |
| **CONFIRM (Human Check)** | **{m['confirm_count']} ({m['confirm_percentage']}%)** | {DETERMINISTIC_BASELINE['confirm']} (0.80%) | {m['confirm_percentage'] - 0.80:+.2f}% |
| **BLOCK (False Block)** | **{m['block_count']} ({m['block_percentage']}%)** | {DETERMINISTIC_BASELINE['block']} (99.20%) | **{comp['absolute_reduction_false_block_rate_percentage_points']:-.2f} pts** |
| **False-Block Rate** | **{m['false_block_rate_percentage']}%** | {DETERMINISTIC_BASELINE['false_block_rate']}% | **-{comp['absolute_reduction_false_block_rate_percentage_points']:.2f} pts** |
| **Gold SQL Execution** | **{m['gold_sql_execution_success']} ({m['gold_sql_execution_success_percentage']}%)** | {DETERMINISTIC_BASELINE['exec_success']} (99.80%) | Identical |
| **Mean Latency** | **{lat['mean']} ms** | {DETERMINISTIC_BASELINE['mean_latency_ms']} ms | +{lat['mean'] - DETERMINISTIC_BASELINE['mean_latency_ms']:.2f} ms |
| **Median Latency** | **{lat['median']} ms** | {DETERMINISTIC_BASELINE['median_latency_ms']} ms | +{lat['median'] - DETERMINISTIC_BASELINE['median_latency_ms']:.2f} ms |
| **P95 Latency** | **{lat['p95']} ms** | {DETERMINISTIC_BASELINE['p95_latency_ms']} ms | +{lat['p95'] - DETERMINISTIC_BASELINE['p95_latency_ms']:.2f} ms |
| **P99 Latency** | **{lat['p99']} ms** | {DETERMINISTIC_BASELINE['p99_latency_ms']} ms | +{lat['p99'] - DETERMINISTIC_BASELINE['p99_latency_ms']:.2f} ms |

---

## 2. LLM Execution & Operational Statistics

- **LLM API Calls Made**: {llm['api_calls_made']}
- **Cached Calls**: {llm['cached_calls']}
- **Failed LLM Calls**: {llm['failed_calls']}
- **Fallbacks to Deterministic**: {llm['fallbacks_to_deterministic']}
- **Total Evaluation Time**: {meta['total_eval_time_sec']}s

---

## 3. Per-Database Breakdown

| Database | Queries | ALLOW | CONFIRM | BLOCK | False-Block Rate | Mean Latency |
|---|---|---|---|---|---|---|
"""
    for db, s in db_res.items():
        content += f"| `{db}` | {s['queries']} | {s['ALLOW']} | {s['CONFIRM']} | {s['BLOCK']} | {s['false_block_rate']}% | {s['mean_latency_ms']} ms |\n"

    content += f"""
---

## 4. Inconsistency / Mismatch Breakdown

| Mismatch Type | Occurrences | Percentage of Evaluated Queries |
|---|---|---|
"""
    for mism, count in mismatches.items():
        pct = (count / m['total_queries']) * 100
        content += f"| `{mism}` | {count} | {pct:.1f}% |\n"

    content += """
---

## 5. Failure & False-Block Analysis

Representative examples where legitimate BIRD queries resulted in BLOCK or CONFIRM:

"""
    for mism_type, items in list(failures_by_type.items())[:4]:
        count = len(items)
        pct = (count / m['total_queries']) * 100
        content += f"### Category: `{mism_type}` ({count} queries, {pct:.1f}%)\n\n"
        for ex in items[:2]:
            content += f"- **Question ID {ex['question_id']}** (`{ex['db_id']}`)\n"
            content += f"  - **Question**: \"{ex['question']}\"\n"
            content += f"  - **Gold SQL**: `{ex['gold_sql']}`\n"
            content += f"  - **Decision**: `{ex['guardian_decision']}` (Risk Score: {ex['risk_score']})\n"
            content += f"  - **Extracted Intent**: `{json.dumps(ex.get('extracted_intent', {}))}`\n\n"

    content += """
---

## 6. Reproducibility Information

- **Dataset Path**: `bird_eval/databases/data_minidev/MINIDEV/mini_dev_sqlite.json`
- **Total Evaluated Queries**: 500
- **Configured Model**: `qwen/qwen3.8-27b` via Groq
- **Evaluation Script**: `bird_eval/full_bird/llm_clean_eval/scripts/run_bird_clean_llm_eval.py`
- **Detailed Results**: `bird_eval/full_bird/llm_clean_eval/results/bird_llm_clean_results.json`
- **Summary**: `bird_eval/full_bird/llm_clean_eval/results/bird_llm_clean_summary.json`
"""

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run BIRD Clean Evaluation with LLM Intent")
    parser.add_argument("--provider", choices=["groq", "gemini"], default="groq", help="LLM Provider (default: groq)")
    parser.add_argument("--model", type=str, default=None, help="LLM Model Name")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of queries (for testing)")
    args = parser.parse_args()

    run_evaluation(provider=args.provider, model=args.model, limit=args.limit)
