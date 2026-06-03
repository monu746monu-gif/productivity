import sqlite3
from datetime import datetime
from storage import get_db_path


VALID_CATEGORIES = {"productive", "neutral", "distracting"}


def setup_app_preferences_db():
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_preferences (
            app_name TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def set_app_category(app_name: str, category: str):
    category = category.lower().strip()

    if category not in VALID_CATEGORIES:
        return None

    cleaned_app_name = app_name.strip()

    if not cleaned_app_name:
        return None

    setup_app_preferences_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO app_preferences (app_name, category, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(app_name) DO UPDATE SET
            category = excluded.category,
            updated_at = excluded.updated_at
        """,
        (cleaned_app_name, category, datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()

    return cleaned_app_name


def get_app_category_override(app_name: str):
    db_path = get_db_path()

    if not db_path.exists():
        return None

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT category
            FROM app_preferences
            WHERE LOWER(?) LIKE '%' || LOWER(app_name) || '%'
               OR LOWER(app_name) LIKE '%' || LOWER(?) || '%'
            ORDER BY LENGTH(app_name) DESC
            LIMIT 1
            """,
            (app_name, app_name),
        )
    except sqlite3.OperationalError:
        conn.close()
        return None

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return row[0]


def get_app_preferences_text():
    setup_app_preferences_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT app_name, category
        FROM app_preferences
        ORDER BY updated_at DESC
        LIMIT 20
        """
    )

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return "No custom app preferences yet."

    return "\n".join(f"{app_name}: {category}" for app_name, category in rows)
