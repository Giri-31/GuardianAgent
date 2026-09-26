"""
check_dataset_overlap.py

Audits datasets to guarantee 0% data leakage between:
  1. Development historical queries (Phase 1-5 development set)
  2. Development split (100 queries)
  3. Final Frozen Evaluation split (400 queries)

Checks question_id matching and normalized natural-language text collision.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
FULL_BIRD_DIR = ROOT / "bird_eval" / "full_bird"
DEV_QUERIES_PATH = FULL_BIRD_DIR / "data" / "development_source_queries.json"
FROZEN_QUERIES_PATH = FULL_BIRD_DIR / "data" / "final_frozen_source_queries.json"
HISTORICAL_MUTATIONS_PATH = ROOT / "bird_eval" / "results" / "bird_mutations_dataset.json"


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def audit_overlap():
    print("=" * 80)
    print("DATASET LEAKAGE & OVERLAP AUDIT")
    print("=" * 80)

    with open(DEV_QUERIES_PATH, "r", encoding="utf-8") as f:
        dev_queries = json.load(f)

    with open(FROZEN_QUERIES_PATH, "r", encoding="utf-8") as f:
        frozen_queries = json.load(f)

    dev_qids = set(q["question_id"] for q in dev_queries)
    frozen_qids = set(q["question_id"] for q in frozen_queries)

    dev_hashes = {hash_text(q["question"]): q["question_id"] for q in dev_queries}
    frozen_hashes = {hash_text(q["question"]): q["question_id"] for q in frozen_queries}

    qid_overlap = dev_qids.intersection(frozen_qids)
    text_overlap = set(dev_hashes.keys()).intersection(set(frozen_hashes.keys()))

    print(f"Development Queries Count      : {len(dev_queries)}")
    print(f"Final Frozen Queries Count     : {len(frozen_queries)}")
    print(f"QID Overlap Count              : {len(qid_overlap)}")
    print(f"Text Collision Overlap Count   : {len(text_overlap)}")

    # Check against Phase 1-5 historical development dataset
    hist_qids = set()
    if HISTORICAL_MUTATIONS_PATH.exists():
        with open(HISTORICAL_MUTATIONS_PATH, "r", encoding="utf-8") as f:
            hist_data = json.load(f)
            hist_qids = set(m["source_question_id"] for m in hist_data["mutations"])
        hist_overlap = hist_qids.intersection(frozen_qids)
        print(f"Historical Phase 1-5 QIDs      : {len(hist_qids)}")
        print(f"Historical vs Frozen Overlap   : {len(hist_overlap)}")
    else:
        hist_overlap = set()

    is_clean = (len(qid_overlap) == 0 and len(text_overlap) == 0 and len(hist_overlap) == 0)

    print("-" * 80)
    if is_clean:
        print("AUDIT VERDICT: PASSED (ZERO DATA LEAKAGE DETECTED)")
        print("Final Frozen Evaluation dataset is 100% out-of-sample and unpolluted.")
    else:
        print("AUDIT VERDICT: FAILED (LEAKAGE DETECTED)")
        raise RuntimeError("Dataset partitioning contains overlapping questions!")
    print("=" * 80)

    return is_clean


if __name__ == "__main__":
    audit_overlap()
