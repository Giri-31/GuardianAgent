from dbbench_loader import load_dbbench
from sql_analyzer import analyze_sql


tasks = load_dbbench()

prepared_tasks = []

for task in tasks:

    sql_info = analyze_sql(task["reference_sql"])

    prepared_tasks.append({
        "description": task["description"],
        "reference_sql": task["reference_sql"],
        "operation": sql_info["operation"],
        "table": task["table"],
        "type": task["type"]
    })


print("Total prepared tasks:", len(prepared_tasks))

print()

for i in range(min(5, len(prepared_tasks))):

    task = prepared_tasks[i]

    print("=" * 60)
    print("TASK", i + 1)
    print("Description:", task["description"])
    print("Operation:", task["operation"])
    print("Reference SQL:", task["reference_sql"])
    print("Type:", task["type"])