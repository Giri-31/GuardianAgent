"""
build_full_bird_inventory.py

Inventories all available BIRD Mini-Dev SQLite data and produces deterministic,
leakage-free partitions for:
  1. Development Split (100 source queries)
  2. Final Frozen Evaluation Split (400 unseen source queries)

Outputs:
  bird_eval/full_bird/results/bird_full_inventory.json
  bird_eval/full_bird/data/development_source_queries.json
  bird_eval/full_bird/data/final_frozen_source_queries.json
  bird_eval/full_bird/data/split_metadata.json
"""

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_PATH = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "mini_dev_sqlite.json"
DEV_DATABASES_DIR = ROOT / "bird_eval" / "databases" / "data_minidev" / "MINIDEV" / "dev_databases"
FULL_BIRD_DIR = ROOT / "bird_eval" / "full_bird"
RESULTS_DIR = FULL_BIRD_DIR / "results"
DATA_DIR = FULL_BIRD_DIR / "data"


def inspect_databases(db_dir: Path):
    db_info = {}
    for db_path in sorted(db_dir.glob("*")):
        if not db_path.is_dir() or db_path.name.startswith("."):
            continue
        db_id = db_path.name
        sqlite_files = list(db_path.glob("*.sqlite"))
        if not sqlite_files:
            continue
        sqlite_file = sqlite_files[0]
        try:
            uri = f"file:{sqlite_file.resolve().as_posix()}?mode=ro"
            con = sqlite3.connect(uri, uri=True)
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            tables = [row[0] for row in cur.fetchall()]
            table_details = {}
            for t in tables:
                cur.execute(f'PRAGMA table_info("{t}")')
                cols = [r[1] for r in cur.fetchall()]
                table_details[t] = cols
            con.close()
            db_info[db_id] = {
                "sqlite_file": sqlite_file.name,
                "file_size_bytes": sqlite_file.stat().st_size,
                "num_tables": len(tables),
                "tables": tables,
                "table_columns": table_details,
            }
        except Exception as e:
            db_info[db_id] = {"error": str(e)}
    return db_info


def main():
    print("=" * 80)
    print("BUILDING FULL BIRD INVENTORY & DATASET PARTITIONS")
    print("=" * 80)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        all_queries = json.load(f)

    total_queries = len(all_queries)
    print(f"Loaded {total_queries} source queries from: {DATA_PATH}")

    # Inspect database schemas
    db_catalog = inspect_databases(DEV_DATABASES_DIR)
    print(f"Cataloged {len(db_catalog)} local SQLite databases.\n")

    # Partitioning:
    # 1. Development split: indices 0 to 99 (100 queries)
    # 2. Final Frozen Evaluation split: indices 100 to 499 (400 queries)
    dev_queries = all_queries[:100]
    frozen_queries = all_queries[100:]

    dev_qids = set(q["question_id"] for q in dev_queries)
    frozen_qids = set(q["question_id"] for q in frozen_queries)

    overlap = dev_qids.intersection(frozen_qids)
    assert len(overlap) == 0, f"Critical error: Data leakage detected! Overlapping QIDs: {overlap}"

    print(f"Development Split        : {len(dev_queries)} queries (Indices 0..99)")
    print(f"Final Frozen Eval Split  : {len(frozen_queries)} queries (Indices 100..499)")
    print(f"Leakage / Overlap Check  : 0 overlapping query IDs (PASSED)\n")

    # Difficulty and database distributions
    dev_dbs = Counter(q["db_id"] for q in dev_queries)
    frozen_dbs = Counter(q["db_id"] for q in frozen_queries)

    dev_diff = Counter(q.get("difficulty", "unknown") for q in dev_queries)
    frozen_diff = Counter(q.get("difficulty", "unknown") for q in frozen_queries)

    inventory_payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_dataset": "birdsql/bird_mini_dev",
            "source_file": str(DATA_PATH),
            "total_source_queries": total_queries,
            "total_databases": len(db_catalog),
        },
        "database_catalog": db_catalog,
        "splits": {
            "development": {
                "count": len(dev_queries),
                "index_range": "0..99",
                "database_distribution": dict(dev_dbs),
                "difficulty_distribution": dict(dev_diff),
                "sample_question_ids": [q["question_id"] for q in dev_queries[:5]],
            },
            "final_frozen_evaluation": {
                "count": len(frozen_queries),
                "index_range": "100..499",
                "database_distribution": dict(frozen_dbs),
                "difficulty_distribution": dict(frozen_diff),
                "sample_question_ids": [q["question_id"] for q in frozen_queries[:5]],
            },
        },
        "leakage_verification": {
            "dev_unique_qids": len(dev_qids),
            "frozen_unique_qids": len(frozen_qids),
            "overlap_count": len(overlap),
            "status": "PASSED_ZERO_LEAKAGE",
        },
    }

    # Save outputs
    inventory_file = RESULTS_DIR / "bird_full_inventory.json"
    with open(inventory_file, "w", encoding="utf-8") as f:
        json.dump(inventory_payload, f, indent=2)

    dev_file = DATA_DIR / "development_source_queries.json"
    with open(dev_file, "w", encoding="utf-8") as f:
        json.dump(dev_queries, f, indent=2)

    frozen_file = DATA_DIR / "final_frozen_source_queries.json"
    with open(frozen_file, "w", encoding="utf-8") as f:
        json.dump(frozen_queries, f, indent=2)

    meta_file = DATA_DIR / "split_metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(inventory_payload["splits"], f, indent=2)

    print("Saved files:")
    print(f"  - Inventory: {inventory_file}")
    print(f"  - Dev Queries: {dev_file}")
    print(f"  - Frozen Queries: {frozen_file}")
    print(f"  - Split Metadata: {meta_file}")
    print("\nDatabase Distribution in Final Frozen Split:")
    for db, cnt in frozen_dbs.most_common():
        print(f"  {db:<26}: {cnt} queries")


if __name__ == "__main__":
    main()
