from dbbench_loader import load_dbbench
from collections import Counter


tasks = load_dbbench()

operations = []

for task in tasks:
    operations.extend(task["type"])

counts = Counter(operations)

print("Total tasks:", len(tasks))
print()
print("Operation distribution:")

for operation, count in counts.items():
    print(operation, ":", count)