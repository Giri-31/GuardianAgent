import os
os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STANDARD"
import sys
sys.path.insert(0, ".")
import controlled_tests

import intent_analyzer
import intent_sql_checker
import risk_engine
from scratch.test_refined_calibration import (
    clean_with_stopwords,
    refined_extract_descriptor_identifier,
    refined_check_filter_target,
    calibrated_overrides
)

intent_analyzer._clean = clean_with_stopwords
intent_analyzer._extract_descriptor_identifier = refined_extract_descriptor_identifier
intent_sql_checker._check_filter_target = refined_check_filter_target
risk_engine._apply_safety_overrides = calibrated_overrides

os.environ["GUARDIAN_READ_SAFETY_LEVEL"] = "STANDARD"

correct = 0
for t in controlled_tests.tests:
    res = controlled_tests.guardian_check(
        user_request=t["request"],
        sql=t["sql"],
        known_intent=t.get("intent"),
        table_name="employees"
    )
    act = res["risk"]["decision"]
    exp = t["expected"]
    if act == exp:
        correct += 1
    else:
        print(f"FAIL: {t['name']} | Expected: {exp}, Actual: {act}")

print(f"Controlled tests: {correct}/{len(controlled_tests.tests)} ({correct/len(controlled_tests.tests)*100:.1f}%)")
