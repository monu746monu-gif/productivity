import sqlite3
from storage import get_db_path

conn = sqlite3.connect(get_db_path())
cursor = conn.cursor()

cursor.execute("SELECT app_name, timestamp FROM app_usage ORDER BY id DESC LIMIT 20")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()
