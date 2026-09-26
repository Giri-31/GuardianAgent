import sys
sys.path.insert(0, ".")
from sql_analyzer import analyze_sql
from intent_sql_checker import check_intent_sql

sql = "SELECT COUNT(DISTINCT T2.School) FROM satscores AS T1 INNER JOIN schools AS T2 ON T1.cds = T2.CDSCode WHERE T2.Virtual = 'F' AND T1.AvgScrMath > 400"
req = "How many schools with an average score in Math greater than 400 in the SAT test are exclusively virtual?"
info = analyze_sql(sql)
print("sql_info fields:", info.get("fields"))
intent = {"operation": "SELECT", "target": "schools", "field": "unknown", "raw_request": req}
res = check_intent_sql(intent, sql)
print("mismatches:", res["mismatches"])
