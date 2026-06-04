import sqlite3
from datetime import datetime

from storage import get_db_path


def setup_social_posts_db():
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS social_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            source_text TEXT NOT NULL,
            draft_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def save_social_post(platform: str, source_text: str, draft_text: str):
    setup_social_posts_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO social_posts (platform, source_text, draft_text, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (platform.strip().lower(), source_text.strip(), draft_text.strip(), datetime.now().isoformat()),
    )

    conn.commit()
    conn.close()


def get_latest_social_post(platform: str):
    setup_social_posts_db()

    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, platform, source_text, draft_text, created_at
        FROM social_posts
        WHERE platform = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (platform.strip().lower(),),
    )

    row = cursor.fetchone()
    conn.close()
    return row
