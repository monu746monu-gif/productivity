import sqlite3
from datetime import datetime
from storage import get_db_path


def setup_ideas_db():
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_idea(content: str):
    setup_ideas_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO ideas (content, created_at) VALUES (?, ?)",
        (content, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


def get_recent_ideas(limit=10):
    setup_ideas_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, content, created_at
        FROM ideas
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_ideas_text():
    ideas = get_recent_ideas()

    if not ideas:
        return "No ideas saved yet."

    lines = []

    for idea_id, content, created_at in ideas:
        lines.append(f"{idea_id}. {content}")

    return "\n".join(lines)
