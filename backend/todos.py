import sqlite3
from datetime import datetime

DB_NAME = "vexa.db"


def setup_todo_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_todo(title: str):
    setup_todo_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO todos (title, completed, created_at) VALUES (?, ?, ?)",
        (title, 0, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


def get_todos():
    setup_todo_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, completed
        FROM todos
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_todos_text():
    todos = get_todos()

    if not todos:
        return "No todos yet."

    lines = []

    for todo_id, title, completed in todos:
        status = "done" if completed else "pending"
        lines.append(f"{todo_id}. {title} - {status}")

    return "\n".join(lines)


def delete_todo_by_text(search_text: str):
    setup_todo_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, title
        FROM todos
        WHERE LOWER(title) LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"%{search_text.lower()}%",)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    todo_id, title = row

    cursor.execute(
        "DELETE FROM todos WHERE id = ?",
        (todo_id,)
    )

    conn.commit()
    conn.close()

    return title


def complete_todo_by_text(search_text: str):
    setup_todo_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, title
        FROM todos
        WHERE LOWER(title) LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"%{search_text.lower()}%",)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    todo_id, title = row

    cursor.execute(
        "UPDATE todos SET completed = 1 WHERE id = ?",
        (todo_id,)
    )

    conn.commit()
    conn.close()

    return title