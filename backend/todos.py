import sqlite3
from datetime import datetime
from storage import get_db_path


def setup_todo_db():
    conn = sqlite3.connect(get_db_path())
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

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO todos (title, completed, created_at) VALUES (?, ?, ?)",
        (title, 0, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


def get_todos():
    setup_todo_db()

    conn = sqlite3.connect(get_db_path())
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


def get_todos_by_status(completed: bool):
    setup_todo_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, title, completed
        FROM todos
        WHERE completed = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (1 if completed else 0,),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_pending_todos():
    return get_todos_by_status(False)


def get_done_todos():
    return get_todos_by_status(True)


def format_todo_rows(rows, empty_text: str):
    if not rows:
        return empty_text

    return "\n".join(f"{todo_id}. {title}" for todo_id, title, _completed in rows)


def get_pending_todos_text():
    return format_todo_rows(get_pending_todos(), "No pending tasks.")


def get_done_todos_text():
    return format_todo_rows(get_done_todos(), "No completed tasks yet.")


def delete_todo_by_text(search_text: str):
    setup_todo_db()

    conn = sqlite3.connect(get_db_path())
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


def delete_all_todos():
    setup_todo_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, title
        FROM todos
        ORDER BY id DESC
        """
    )

    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return []

    todo_ids = [todo_id for todo_id, _title in rows]
    placeholders = ",".join("?" for _todo_id in todo_ids)

    cursor.execute(
        f"DELETE FROM todos WHERE id IN ({placeholders})",
        todo_ids,
    )

    conn.commit()
    conn.close()

    return [title for _todo_id, title in rows]


def complete_todo_by_text(search_text: str):
    setup_todo_db()

    conn = sqlite3.connect(get_db_path())
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


def complete_single_pending_todo():
    pending_todos = get_pending_todos()

    if len(pending_todos) != 1:
        return None

    todo_id, title, _completed = pending_todos[0]

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE todos SET completed = 1 WHERE id = ?",
        (todo_id,)
    )

    conn.commit()
    conn.close()

    return title
