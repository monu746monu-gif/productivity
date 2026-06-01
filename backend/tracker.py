import time
import sqlite3
import subprocess
from datetime import datetime, timedelta


DB_NAME = "vexa.db"
TRACKER_INTERVAL_SECONDS = 5
RESET_AFTER_HOURS = 20


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


def cleanup_old_usage():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cutoff_time = (datetime.now() - timedelta(hours=RESET_AFTER_HOURS)).isoformat()

    cursor.execute(
        "DELETE FROM app_usage WHERE timestamp < ?",
        (cutoff_time,)
    )

    conn.commit()
    conn.close()


def start_tracker(interval=TRACKER_INTERVAL_SECONDS):
    setup_db()

    print("Vexa tracker started...")
    print(f"Tracking every {interval} seconds.")
    print(f"Keeping only last {RESET_AFTER_HOURS} hours of data.")
    print("Press Ctrl + C to stop.")

    loop_count = 0

    while True:
        app_name = get_active_app()
        save_app_usage(app_name)

        print(f"Tracked: {app_name}")

        loop_count += 1

        # Cleanup every 5 minutes when interval is 5 seconds
        if loop_count % 60 == 0:
            cleanup_old_usage()
            print("Old usage data cleaned.")

        time.sleep(interval)


if __name__ == "__main__":
    start_tracker()