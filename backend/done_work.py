import sqlite3
from datetime import datetime

from storage import get_db_path


def setup_done_work_db():
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS done_work (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def save_done_work(title: str):
    cleaned_title = title.strip()

    if not cleaned_title:
        return

    setup_done_work_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO done_work (title, created_at) VALUES (?, ?)",
        (cleaned_title, datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()


def get_done_work(limit=20, only_today=True):
    setup_done_work_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    if only_today:
        today = datetime.now().date().isoformat()
        cursor.execute(
            """
            SELECT id, title, created_at
            FROM done_work
            WHERE substr(created_at, 1, 10) = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (today, limit),
        )
    else:
        cursor.execute(
            """
            SELECT id, title, created_at
            FROM done_work
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )

    rows = cursor.fetchall()
    conn.close()
    return rows


def get_done_work_titles(limit=20, only_today=True):
    rows = get_done_work(limit=limit, only_today=only_today)
    return [title for _row_id, title, _created_at in rows]


def get_done_work_text(limit=20, only_today=True):
    titles = get_done_work_titles(limit=limit, only_today=only_today)

    if not titles:
        return "No productive work logged yet."

    return "\n".join(f"{index + 1}. {title}" for index, title in enumerate(titles))
