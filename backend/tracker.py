import time
import sqlite3
import subprocess
from datetime import datetime


DB_NAME = "vexa.db"


def get_active_app():
    script = '''
    tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
        return frontApp
    end tell
    '''

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )

    app_name = result.stdout.strip()
    error = result.stderr.strip()

    if error:
        print("AppleScript error:", error)

    if app_name:
        return app_name

    return "Unknown"


def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_app_usage(app_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO app_usage (app_name, timestamp) VALUES (?, ?)",
        (app_name, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


def start_tracker(interval=5):
    setup_db()

    print("Vexa tracker started...")
    print("Switch to another app and stay there for 5 seconds.")
    print("Press Ctrl + C to stop.")

    while True:
        app_name = get_active_app()
        save_app_usage(app_name)

        print(f"Tracked: {app_name}")

        time.sleep(interval)


if __name__ == "__main__":
    start_tracker()