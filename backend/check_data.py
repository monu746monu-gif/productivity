import sqlite3

conn = sqlite3.connect("vexa.db")
cursor = conn.cursor()

cursor.execute("SELECT app_name, timestamp FROM app_usage ORDER BY id DESC LIMIT 20")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()