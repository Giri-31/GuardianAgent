import json


DBBENCH_FILE = r"D:\Git\AgentBench\data\dbbench\dev.jsonl"


def load_dbbench():

    tasks = []

    with open(DBBENCH_FILE, "r", encoding="utf-8") as file:

        for line in file:

            task = json.loads(line)

            if "sql" in task:

                sql_data = task["sql"]

                if isinstance(sql_data, dict):
                    sql = sql_data.get("query", "")
                else:
                    sql = sql_data

            elif "label" in task:

                label = task["label"]

                if isinstance(label, list) and len(label) > 0:
                    sql = label[0]
                else:
                    sql = label

            else:
                continue

            if not sql:
                continue

            tasks.append({
                "description": task.get("description", ""),
                "sql": sql,
                "table": task.get("table", {}),
                "evaluation": task.get("evaluation", ""),
                "type": task.get("type", []),
                "source": task.get("source", "")
            })

    return tasks


if __name__ == "__main__":

    tasks = load_dbbench()

    print("Total DBBench tasks:", len(tasks))

    print()
    print("First task:")
    print("Description:", tasks[0]["description"])
    print("SQL:", tasks[0]["sql"])
    print("Type:", tasks[0]["type"])

    print()
    print("Last task:")
    print("Description:", tasks[-1]["description"])
    print("SQL:", tasks[-1]["sql"])
    print("Type:", tasks[-1]["type"])