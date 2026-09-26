import os
import sys
from pathlib import Path
os.environ["GUARDIAN_DISABLE_LLM"] = "1"
sys.path.insert(0, ".")

from bird_eval.scripts.guardian_adapter import GuardianBIRDAdapter

DEV_DATABASES_DIR = Path("bird_eval/databases/data_minidev/MINIDEV/dev_databases")
db_path = DEV_DATABASES_DIR / "california_schools" / "california_schools.sqlite"

req = "How many schools with an average score in Math greater than 400 in the SAT test are exclusively virtual?"
sql = "SELECT COUNT(DISTINCT T2.School) FROM satscores AS T1 INNER JOIN schools AS T2 ON T1.cds = T2.CDSCode WHERE T2.Virtual = 'F' AND T1.AvgScrMath > 400"

adapter = GuardianBIRDAdapter(disable_llm_intent=True)
conn = adapter.open_database_connection(db_path, read_only=True)
res = adapter.evaluate_query(req, sql, connection=conn)
conn.close()

print("Decision:", res["decision"])
print("Risk score:", res["risk_score"])
print("Mismatches:", res["mismatches"])
print("Intent:", res["intent"])
print("SQL Info:", res["sql_info"])
