import sqlite3
import re
from datetime import datetime, timedelta

DB_NAME = "vexa.db"


def parse_reminder_time(reminder_time: str):
    text = reminder_time.strip().lower()
    now = datetime.now()

    date_value = now.date()

    if "tomorrow" in text:
        date_value = (now + timedelta(days=1)).date()

    time_match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b",
        text,
    )

    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    meridiem = time_match.group(3)

    if minute > 59:
        return None

    if meridiem:
        meridiem = meridiem.replace(".", "")

        if hour < 1 or hour > 12:
            return None

        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        return None

    remind_at = datetime.combine(date_value, datetime.min.time()).replace(
        hour=hour,
        minute=minute,
    )

    if remind_at <= now and "today" not in text and "tomorrow" not in text:
        remind_at += timedelta(days=1)

    return remind_at


def format_reminder_time(remind_at: str):
    try:
        parsed = datetime.fromisoformat(remind_at)
        return parsed.strftime("%b %d at %-I:%M %p")
    except ValueError:
        return remind_at


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


def pop_due_reminders():
    due_reminders = get_due_reminders()

    for reminder_id, _, _ in due_reminders:
        mark_reminder_done(reminder_id)

    return [
        {
            "id": reminder_id,
            "title": title,
            "remind_at": remind_at,
            "display_time": format_reminder_time(remind_at),
        }
        for reminder_id, title, remind_at in due_reminders
    ]


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
        lines.append(f"{reminder_id}. {title} at {format_reminder_time(remind_at)}")

    return "\n".join(lines)
