import time
import sqlite3
import subprocess
import re
from datetime import datetime, timedelta
from productivity import classify_app
from storage import get_db_path

TRACKER_INTERVAL_SECONDS = 5
KEEP_HISTORY_DAYS = 14
FOCUS_ALERT_COOLDOWN_SECONDS = 180
VEXA_SAY_VOICE = "Samantha"

last_focus_alerts = {}
GENERIC_APP_NAMES = {
    "app_mode_loader",
    "App Mode Loader",
}


def run_osascript(script: str):
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )

    output = result.stdout.strip()
    error = result.stderr.strip()

    if error:
        print("AppleScript error:", error)

    if result.returncode != 0:
        return ""

    return output


def simplify_window_title(window_title: str):
    cleaned = window_title.strip()

    if not cleaned:
        return ""

    cleaned = re.sub(r"^[\(\[]?\d+[\)\]]?\s+", "", cleaned)
    cleaned = re.sub(r"\s*[\*•·]+\s*$", "", cleaned)

    for separator in (" - ", " — ", " | ", " · ", " : "):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
            break

    known_titles = (
        "Claude",
        "Excalidraw",
        "ChatGPT",
        "Notion",
        "Figma",
        "Linear",
        "Slack",
    )

    lowered = cleaned.lower()

    for title in known_titles:
        if title.lower() in lowered:
            return title

    if 0 < len(cleaned) <= 60:
        return cleaned

    return ""


def normalize_active_app_name(app_name: str, bundle_id: str, window_title: str):
    cleaned_name = app_name.strip()

    if cleaned_name not in GENERIC_APP_NAMES:
        return cleaned_name or "Unknown"

    inferred_name = simplify_window_title(window_title)

    if inferred_name:
        return inferred_name

    if bundle_id.startswith("com.google.Chrome.app."):
        return "Chrome App"

    return cleaned_name or "Unknown"


def get_active_app():
    script = '''
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set bundleId to ""
        set windowTitle to ""

        try
            set bundleId to bundle identifier of frontApp
        end try

        try
            if (count of windows of frontApp) > 0 then
                set windowTitle to name of front window of frontApp
            end if
        end try

        return appName & "||" & bundleId & "||" & windowTitle
    end tell
    '''

    app_snapshot = run_osascript(script)

    if app_snapshot:
        app_name, bundle_id, window_title = (
            (app_snapshot.split("||", 2) + ["", ""])[:3]
        )
        normalized_name = normalize_active_app_name(app_name, bundle_id, window_title)

        if normalized_name:
            return normalized_name

    return "Unknown"


def setup_db():
    conn = sqlite3.connect(get_db_path())
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
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO app_usage (app_name, timestamp) VALUES (?, ?)",
        (app_name, datetime.now().isoformat())
    )

    conn.commit()
    conn.close()


def speak_focus_alert(app_name):
    message = (
        f"Misu, nooo. You marked {app_name} as distracting. "
        "Quit this now. You have work to do. Don't you want to live a better life?"
    )

    subprocess.Popen(
        ["say", "-v", VEXA_SAY_VOICE, message],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def maybe_alert_for_distracting_app(app_name):
    if classify_app(app_name) != "distracting":
        return

    now = datetime.now()
    last_alert_at = last_focus_alerts.get(app_name)

    if last_alert_at and (now - last_alert_at).total_seconds() < FOCUS_ALERT_COOLDOWN_SECONDS:
        return

    last_focus_alerts[app_name] = now
    speak_focus_alert(app_name)


def cleanup_old_usage():
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    cutoff_date = (datetime.now().date() - timedelta(days=KEEP_HISTORY_DAYS)).isoformat()

    cursor.execute(
        "DELETE FROM app_usage WHERE substr(timestamp, 1, 10) < ?",
        (cutoff_date,)
    )

    conn.commit()
    conn.close()


def start_tracker(interval=TRACKER_INTERVAL_SECONDS):
    setup_db()

    print("Vexa tracker started...")
    print(f"Tracking every {interval} seconds.")
    print(f"Today starts from 0 at midnight. Keeping {KEEP_HISTORY_DAYS} days of history.")
    print("Press Ctrl + C to stop.")

    loop_count = 0

    while True:
        app_name = get_active_app()
        save_app_usage(app_name)
        maybe_alert_for_distracting_app(app_name)

        print(f"Tracked: {app_name}")

        loop_count += 1

        # Cleanup every 5 minutes when interval is 5 seconds
        if loop_count % 60 == 0:
            cleanup_old_usage()
            print("Old usage data cleaned.")

        time.sleep(interval)


if __name__ == "__main__":
    start_tracker()
