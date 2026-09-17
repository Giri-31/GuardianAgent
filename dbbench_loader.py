import json
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DBBENCH_FILE = os.path.join(
    BASE_DIR,
    "AgentBenchData",
    "data",
    "dbbench",
    "dev.jsonl"
)


def load_dbbench():

    tasks = []

    with open(
        DBBENCH_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        for index, line in enumerate(file, start=1):

            line = line.strip()

            if not line:
                continue

            task = json.loads(line)

            sql_data = task.get("sql", "")

            if isinstance(sql_data, dict):
                reference_sql = sql_data.get(
                    "query",
                    ""
                )
            else:
                reference_sql = sql_data

            tasks.append({
                "case_id": index,

                "description": task.get(
                    "description",
                    ""
                ),

                "label": task.get(
                    "label",
                    []
                ),

                "reference_sql": reference_sql,

                "table": task.get(
                    "table",
                    {}
                ),

                "create": task.get(
                    "create",
                    {}
                ),

                "evaluation": task.get(
                    "evaluation",
                    ""
                ),

                "type": task.get(
                    "type",
                    []
                ),

                "source": task.get(
                    "source",
                    ""
                )
            })

    return tasks