import sqlite3

db_path = (
    "bird_eval/databases/data_minidev/"
    "MINIDEV/dev_databases/debit_card_specializing/"
    "debit_card_specializing.sqlite"
)

conn = sqlite3.connect(db_path)

query = """
SELECT CAST(SUM(IIF(Currency = 'EUR', 1, 0)) AS FLOAT)
       / SUM(IIF(Currency = 'CZK', 1, 0)) AS ratio
FROM customers
"""

result = conn.execute(query).fetchone()

print("BIRD gold SQL result:")
print(result)

conn.close()