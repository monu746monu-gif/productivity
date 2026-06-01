import sqlite3
from datetime import datetime

DB_NAME = "vexa.db"


def setup_reminders_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_reminder(title: str, remind_at: str):
    setup_reminders_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO reminders (title, remind_at, completed, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (title, remind_at, 0, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


def get_due_reminders():
    setup_reminders_db()

    now = datetime.now().isoformat()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, title, remind_at
        FROM reminders
        WHERE completed = 0 AND remind_at <= ?
        ORDER BY remind_at ASC
        """,
        (now,)
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def mark_reminder_done(reminder_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE reminders SET completed = 1 WHERE id = ?",
        (reminder_id,)
    )

    conn.commit()
    conn.close()


def get_reminders_text():
    setup_reminders_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, title, remind_at
        FROM reminders
        WHERE completed = 0
        ORDER BY remind_at ASC
        LIMIT 10
        """
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "No upcoming reminders."

    lines = []

    for reminder_id, title, remind_at in rows:
        lines.append(f"{reminder_id}. {title} at {remind_at}")

    return "\n".join(lines)