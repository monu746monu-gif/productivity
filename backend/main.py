import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from storage import get_db_path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from intent import (
    TIME_PATTERN,
    detect_intent,
    has_idea_discussion_language,
    has_idea_language,
    has_reminder_language,
    has_todo_language,
    strip_command_words,
)
from ideas import save_idea, get_ideas_text
from done_work import save_done_work, get_done_work_titles, get_done_work_text
from social_posts import save_social_post, get_latest_social_post
from productivity import classify_app
from app_preferences import set_app_category, get_app_preferences_text
from recorder import record_audio
from reminders import (
    add_reminder,
    get_reminders_text,
    parse_reminder_time,
    pop_due_reminders,
)
from settings_store import (
    get_openai_api_key,
    has_openai_api_key,
    is_openai_api_key_managed,
)
from todos import (
    add_todo,
    get_todos_text,
    get_pending_todos_text,
    get_done_todos_text,
    delete_todo_by_text,
    delete_all_todos,
    complete_todo_by_text,
    complete_single_pending_todo,
)

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


TRACKER_INTERVAL_SECONDS = 5
USAGE_HISTORY_DAYS = 14
VOICE_RECORD_SECONDS = 10
FOCUS_ALERT_COOLDOWN_SECONDS = 180
FOCUS_ALERT_LOOKBACK_SECONDS = 60


class ChatRequest(BaseModel):
    message: str


class ApiKeyRequest(BaseModel):
    api_key: str


pending_action = {
    "type": "",
    "title": "",
    "platform": "",
}

conversation_memory = []
last_focus_alerts = {}


FRIENDLY_VOICE_STYLE = """
Conversation style:
- Talk like a real person who is present with Misu, not like a formal report.
- Keep voice replies short, warm, and natural: usually 1 to 3 sentences.
- If Misu shares his day, mood, plans, time, or random thoughts, respond like a thoughtful friend.
- Ask one gentle follow-up question when it would keep the conversation flowing.
- For casual chat, do not turn the answer into productivity advice unless Misu asks for it.
- Use simple words, natural spoken rhythm, and light Hinglish only when it fits.
- If Misu says he wants to talk for some time, settle into conversation and invite him to continue.
- Do not over-explain.
- Do not use markdown, numbered lists, or long paragraphs in voice replies.
"""


VOICE_TRANSCRIPTION_PROMPT = (
    "The user is speaking English or Hinglish to an AI productivity "
    "assistant named Vexa. Terms may include Cursor, Chrome, Terminal, "
    "productivity, todo, checklist, app usage, work time, delete task, "
    "remove task, mark task done, pending tasks, completed tasks, "
    "daily report, productivity summary, how was my day, save idea, "
    "remember idea, meeting, call, and reminder."
)


@app.get("/")
def health_check():
    return {"status": "Vexa backend is running"}


def get_openai_client():
    api_key = get_openai_api_key()

    if not api_key:
        return None

    return OpenAI(api_key=api_key)


def missing_api_key_reply():
    return {
        "reply": "Vexa is not configured with the server OpenAI API key yet.",
        "missing_api_key": True,
    }


@app.get("/settings")
def get_settings():
    return {
        "openai_api_key_configured": has_openai_api_key(),
        "openai_api_key_managed": is_openai_api_key_managed(),
    }


@app.post("/settings/openai-key")
def set_openai_key(request: ApiKeyRequest):
    return {
        "saved": False,
        "error": "API keys are managed by the Vexa backend.",
        "openai_api_key_configured": has_openai_api_key(),
        "openai_api_key_managed": True,
    }


def today_date():
    return datetime.now().date()


def cleanup_old_usage_history():
    conn = sqlite3.connect(get_db_path(), timeout=1)
    cursor = conn.cursor()

    cutoff_date = (today_date() - timedelta(days=USAGE_HISTORY_DAYS)).isoformat()

    cursor.execute(
        "DELETE FROM app_usage WHERE substr(timestamp, 1, 10) < ?",
        (cutoff_date,),
    )
    conn.commit()
    conn.close()


def get_usage_rows_for_date(day):
    cleanup_old_usage_history()

    conn = sqlite3.connect(get_db_path(), timeout=1)
    cursor = conn.cursor()

    start_time = datetime.combine(day, datetime.min.time())
    end_time = start_time + timedelta(days=1)

    cursor.execute(
        """
        SELECT app_name, COUNT(*) as count
        FROM app_usage
        WHERE timestamp >= ? AND timestamp < ?
        GROUP BY app_name
        ORDER BY count DESC
        """,
        (start_time.isoformat(), end_time.isoformat()),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_usage_rows():
    return get_usage_rows_for_date(today_date())


def get_latest_usage_entry():
    conn = sqlite3.connect(get_db_path(), timeout=1)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT app_name, timestamp
        FROM app_usage
        ORDER BY timestamp DESC
        LIMIT 1
        """
    )

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    app_name, timestamp = row

    try:
        tracked_at = datetime.fromisoformat(timestamp)
    except ValueError:
        tracked_at = datetime.now()

    return {
        "app_name": app_name,
        "timestamp": timestamp,
        "tracked_at": tracked_at,
    }


def get_recent_usage_entries(seconds: int):
    cutoff = datetime.now() - timedelta(seconds=seconds)
    conn = sqlite3.connect(get_db_path(), timeout=1)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT app_name, timestamp
        FROM app_usage
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT 30
        """,
        (cutoff.isoformat(),),
    )

    rows = cursor.fetchall()
    conn.close()

    entries = []

    for app_name, timestamp in rows:
        try:
            tracked_at = datetime.fromisoformat(timestamp)
        except ValueError:
            tracked_at = datetime.now()

        entries.append(
            {
                "app_name": app_name,
                "timestamp": timestamp,
                "tracked_at": tracked_at,
            }
        )

    return entries


def get_focus_alert_for_latest_app():
    recent_entries = get_recent_usage_entries(FOCUS_ALERT_LOOKBACK_SECONDS)
    latest = recent_entries[0] if recent_entries else get_latest_usage_entry()

    if not latest:
        return {
            "alert": False,
            "app_name": "",
            "message": "",
            "reason": "No app usage has been tracked yet.",
        }

    distracting_entry = None

    for entry in recent_entries:
        if classify_app(entry["app_name"]) == "distracting":
            distracting_entry = entry
            break

    if not distracting_entry and latest and classify_app(latest["app_name"]) == "distracting":
        distracting_entry = latest

    app_name = distracting_entry["app_name"] if distracting_entry else latest["app_name"]
    category = classify_app(app_name)

    if category != "distracting":
        return {
            "alert": False,
            "app_name": app_name,
            "category": category,
            "message": "",
            "reason": "Current app is not distracting.",
        }

    now = datetime.now()
    seconds_since_tracking = (now - (distracting_entry or latest)["tracked_at"]).total_seconds()

    if seconds_since_tracking > FOCUS_ALERT_LOOKBACK_SECONDS:
        return {
            "alert": False,
            "app_name": app_name,
            "category": category,
            "message": "",
            "reason": "Latest app usage is stale.",
        }

    last_alert_at = last_focus_alerts.get(app_name)

    if last_alert_at and (now - last_alert_at).total_seconds() < FOCUS_ALERT_COOLDOWN_SECONDS:
        return {
            "alert": False,
            "app_name": app_name,
            "category": category,
            "message": "",
            "reason": "Focus alert is cooling down.",
        }

    last_focus_alerts[app_name] = now

    message = (
        f"Misu, nooo. You marked {app_name} as distracting. "
        "Quit this now. You have work to do. Don't you want to live a better life?"
    )

    return {
        "alert": True,
        "app_name": app_name,
        "category": category,
        "message": message,
        "cooldown_seconds": FOCUS_ALERT_COOLDOWN_SECONDS,
    }


def rows_to_usage_items(rows):
    usage = []

    for app_name, count in rows:
        seconds = count * TRACKER_INTERVAL_SECONDS
        minutes = round(seconds / 60, 2)
        category = classify_app(app_name)

        usage.append(
            {
                "app_name": app_name,
                "seconds": seconds,
                "minutes": minutes,
                "category": category,
            }
        )

    return usage


def get_productivity_totals(rows):
    totals = {
        "productive": 0,
        "neutral": 0,
        "distracting": 0,
    }

    for app_name, count in rows:
        seconds = count * TRACKER_INTERVAL_SECONDS
        minutes = round(seconds / 60, 2)
        category = classify_app(app_name)
        totals[category] += minutes

    return {
        "productive": round(totals["productive"], 2),
        "neutral": round(totals["neutral"], 2),
        "distracting": round(totals["distracting"], 2),
    }


def get_yesterday_date():
    return today_date() - timedelta(days=1)


def get_daily_comparison():
    today_rows = get_usage_rows_for_date(today_date())
    yesterday_rows = get_usage_rows_for_date(get_yesterday_date())
    today_totals = get_productivity_totals(today_rows)
    yesterday_totals = get_productivity_totals(yesterday_rows)

    productive_delta = round(
        today_totals["productive"] - yesterday_totals["productive"],
        2,
    )
    distracting_delta = round(
        today_totals["distracting"] - yesterday_totals["distracting"],
        2,
    )

    return {
        "today": today_totals,
        "yesterday": yesterday_totals,
        "productive_delta": productive_delta,
        "distracting_delta": distracting_delta,
    }


def get_daily_comparison_text():
    comparison = get_daily_comparison()
    productive_delta = comparison["productive_delta"]
    distracting_delta = comparison["distracting_delta"]

    return f"""
Today vs yesterday:
Today productive: {comparison["today"]["productive"]} minutes
Yesterday productive: {comparison["yesterday"]["productive"]} minutes
Productive change: {productive_delta} minutes
Today distracting: {comparison["today"]["distracting"]} minutes
Yesterday distracting: {comparison["yesterday"]["distracting"]} minutes
Distracting change: {distracting_delta} minutes
"""


def get_today_usage_text():
    return get_usage_text_for_date(today_date())


def get_usage_text_for_date(day):
    rows = get_usage_rows_for_date(day)

    if not rows:
        return f"No app usage data has been tracked for {day.isoformat()}."

    usage_lines = []

    for app_name, count in rows:
        seconds = count * TRACKER_INTERVAL_SECONDS
        minutes = round(seconds / 60, 2)
        usage_lines.append(f"{app_name}: {minutes} minutes")

    return "\n".join(usage_lines)


def get_productivity_summary_text():
    rows = get_usage_rows()

    if not rows:
        return "No productivity data has been tracked today."

    totals = {
        "productive": 0,
        "neutral": 0,
        "distracting": 0,
    }

    app_lines = []

    for app_name, count in rows:
        seconds = count * TRACKER_INTERVAL_SECONDS
        minutes = round(seconds / 60, 2)
        category = classify_app(app_name)

        totals[category] += minutes
        app_lines.append(f"{app_name}: {minutes} minutes, {category}")

    productive = round(totals["productive"], 2)
    neutral = round(totals["neutral"], 2)
    distracting = round(totals["distracting"], 2)

    return f"""
Today's productivity summary:
Productive time: {productive} minutes
Neutral time: {neutral} minutes
Distracting time: {distracting} minutes

App breakdown:
{chr(10).join(app_lines)}
"""


def format_duration_minutes(minutes: float):
    minutes = round(minutes, 2)

    if minutes < 1:
        seconds = round(minutes * 60)
        return f"{seconds} seconds"

    hours = int(minutes // 60)
    remaining = round(minutes % 60)

    if hours <= 0:
        minute_label = "minute" if minutes == 1 else "minutes"
        return f"{minutes:g} {minute_label}"

    hour_label = "hour" if hours == 1 else "hours"

    if remaining == 0:
        return f"{hours} {hour_label}"

    minute_label = "minute" if remaining == 1 else "minutes"
    return f"{hours} {hour_label} {remaining} {minute_label}"


def get_top_usage_items(limit=3, category=None):
    items = rows_to_usage_items(get_usage_rows())

    if category:
        items = [item for item in items if item["category"] == category]

    return items[:limit]


def format_top_apps_for_voice(items):
    if not items:
        return ""

    return ", ".join(
        f'{item["app_name"]} for {format_duration_minutes(item["minutes"])}'
        for item in items
    )


def detect_done_work_entry(user_text: str):
    text = user_text.strip()

    patterns = [
        (r"\bi had a meeting with\s+(.+)", "meeting with {value}"),
        (r"\bi had meeting with\s+(.+)", "meeting with {value}"),
        (r"\bi met with\s+(.+)", "meeting with {value}"),
        (r"\bi had a call with\s+(.+)", "call with {value}"),
        (r"\bi spoke with\s+(.+)", "call with {value}"),
    ]

    for pattern, template in patterns:
        match = re.search(pattern, text, flags=re.I)

        if not match:
            continue

        value = match.group(1).strip(" .,:;-")

        if value:
            return template.format(value=value)

    return ""


def is_done_work_query(user_text: str):
    text = user_text.lower()

    return any(
        phrase in text
        for phrase in [
            "what productive work have i done",
            "what productive work i have done",
            "what prod have i done",
            "what work have i done",
            "what have i done for work",
            "what did i finish today",
            "what meetings did i have",
            "what have i completed today",
        ]
    )


def build_done_work_reply():
    logged_work = get_done_work_titles()
    completed_todos_text = get_done_todos_text()

    if not logged_work and completed_todos_text == "No completed tasks yet.":
        return "You have not logged any productive work yet today, Misu."

    reply_parts = []

    if logged_work:
        work_text = ", ".join(logged_work[:5])
        reply_parts.append(f"You logged {work_text}.")

    if completed_todos_text != "No completed tasks yet.":
        reply_parts.append(f"Completed tasks: {completed_todos_text}.")

    return " ".join(reply_parts)


def get_productive_activity_label(app_name: str):
    lowered = app_name.lower()

    if any(name in lowered for name in ["cursor", "visual studio code", "vs code", "xcode", "sublime text"]):
        return "coding"

    if "terminal" in lowered or "iterm" in lowered:
        return "working in"

    if "figma" in lowered:
        return "designing in"

    if "notion" in lowered:
        return "planning in"

    if "postman" in lowered:
        return "testing APIs in"

    return "working in"


def format_productive_highlight(item):
    if not item:
        return ""

    activity = get_productive_activity_label(item["app_name"])

    if activity == "coding":
        return (
            f"You spent most of your productive time coding in {item['app_name']} "
            f"for {format_duration_minutes(item['minutes'])}."
        )

    return (
        f"You spent most of your productive time {activity} {item['app_name']} "
        f"for {format_duration_minutes(item['minutes'])}."
    )


def get_usage_category_answer(user_text: str):
    text = user_text.lower()

    if not any(
        phrase in text
        for phrase in [
            "how much",
            "how many",
            "tell me",
            "what is",
            "what's",
            "spent",
            "spend",
            "usage",
            "time",
            "productive",
            "productivity",
            "focus",
            "work",
        ]
    ):
        return None

    category = None

    if any(word in text for word in ["productive", "productivity", "focus", "focused", "work"]):
        category = "productive"
    elif any(word in text for word in ["distracting", "distraction", "wasted", "waste"]):
        category = "distracting"
    elif "neutral" in text:
        category = "neutral"
    elif any(phrase in text for phrase in ["total time", "all time", "overall time"]):
        category = "total"

    if not category:
        return None

    comparison = get_daily_comparison()
    today = comparison["today"]

    if category == "total":
        total_minutes = round(
            today["productive"] + today["neutral"] + today["distracting"],
            2,
        )
        return f"Misu, I have tracked {format_duration_minutes(total_minutes)} total today."

    category_minutes = today[category]
    category_label = "productive work" if category == "productive" else f"{category} apps"
    reply = f"Misu, you have spent {format_duration_minutes(category_minutes)} on {category_label} today."

    if category == "productive":
        productive_apps = [
            item
            for item in rows_to_usage_items(get_usage_rows())
            if item["category"] == "productive"
        ]

        if productive_apps:
            productive_highlight = format_productive_highlight(productive_apps[0])

            if productive_highlight:
                reply += f" {productive_highlight}"

    return reply


def build_local_usage_reply(user_text: str):
    category_answer = get_usage_category_answer(user_text)

    if category_answer:
        return category_answer

    rows = get_usage_rows()

    if not rows:
        return "I have not tracked any app usage yet today, Misu."

    comparison = get_daily_comparison()
    today = comparison["today"]
    total_minutes = round(
        today["productive"] + today["neutral"] + today["distracting"],
        2,
    )
    top_apps = format_top_apps_for_voice(get_top_usage_items())
    productive_highlight = format_productive_highlight(
        get_top_usage_items(limit=1, category="productive")[0]
    ) if get_top_usage_items(limit=1, category="productive") else ""

    reply = (
        f"Today you spent {format_duration_minutes(today['productive'])} on productive apps, "
        f"{format_duration_minutes(today['neutral'])} on neutral apps, and "
        f"{format_duration_minutes(today['distracting'])} on distracting apps."
    )

    if productive_highlight:
        reply += f" {productive_highlight}"
    elif top_apps:
        reply += f" Your top apps were {top_apps}."

    if total_minutes > 0:
        reply += f" Total tracked time is {format_duration_minutes(total_minutes)}."

    return reply


def build_local_daily_report():
    rows = get_usage_rows()

    if not rows:
        return "I do not have enough tracked data for today yet, Misu."

    comparison = get_daily_comparison()
    today = comparison["today"]
    pending_text = get_pending_todos_text()
    top_apps = format_top_apps_for_voice(get_top_usage_items())
    productive_highlight = format_productive_highlight(
        get_top_usage_items(limit=1, category="productive")[0]
    ) if get_top_usage_items(limit=1, category="productive") else ""

    if comparison["productive_delta"] > 0:
        comparison_line = (
            f"That is {format_duration_minutes(comparison['productive_delta'])} more productive time than yesterday."
        )
    elif comparison["productive_delta"] < 0:
        comparison_line = (
            f"That is {format_duration_minutes(abs(comparison['productive_delta']))} less productive time than yesterday."
        )
    else:
        comparison_line = "Your productive time is almost the same as yesterday."

    if today["productive"] >= today["distracting"]:
        tone = "Overall, your day looks fairly solid."
    else:
        tone = "Overall, the day looks a bit scattered."

    improvement = (
        "Try to protect one focused block and clear one pending task first."
        if pending_text != "No pending tasks."
        else "Try to protect one focused block and avoid distracting apps for a while."
    )

    reply = (
        f"{tone} You spent {format_duration_minutes(today['productive'])} on productive apps and "
        f"{format_duration_minutes(today['distracting'])} on distracting apps."
    )

    if productive_highlight:
        reply += f" {productive_highlight}"
    elif top_apps:
        reply += f" Most of your time went to {top_apps}."

    reply += f" {comparison_line} Pending tasks: {pending_text}. {improvement}"
    return reply


def save_reminder_from_parts(title: str, reminder_time: str):
    remind_at = parse_reminder_time(reminder_time)

    if not remind_at:
        return None

    add_reminder(title, remind_at.isoformat())
    spoken_time = remind_at.strftime("%I:%M %p").lstrip("0")
    return f"Done, Misu. I will remind you about {title} at {spoken_time}."


def clean_social_post_prompt(user_text: str):
    cleaned = strip_command_words(
        user_text,
        [
            "i want to post about",
            "i want to post",
            "post about",
            "post on twitter about",
            "post on twitter",
            "tweet about",
            "tweet",
            "write a post about",
            "write a post",
            "for twitter",
            "on twitter",
            "twitter",
            "x",
            "please",
        ],
    )
    return cleaned.strip(" .,:;-")


def is_twitter_post_request(user_text: str):
    text = user_text.lower()

    return any(
        phrase in text
        for phrase in [
            "schedule a post for twitter",
            "schedule post for twitter",
            "schedule a twitter post",
            "make a post for twitter",
            "write a post for twitter",
            "draft a post for twitter",
            "draft a tweet",
            "write a tweet",
            "make a tweet",
            "schedule a tweet",
            "i want to post on twitter",
            "i want to post for twitter",
            "i want to write a tweet",
            "i want to draft a tweet",
        ]
    )


def is_twitter_post_query(user_text: str):
    text = user_text.lower()

    return any(
        phrase in text
        for phrase in [
            "show my twitter post",
            "show me my twitter post",
            "what is my twitter post",
            "what's my twitter post",
            "give me my twitter post",
            "show my tweet",
            "show me my tweet",
            "what is my tweet",
            "what's my tweet",
            "give me my tweet",
            "twitter draft",
            "tweet draft",
        ]
    )


def build_twitter_post_draft(client, source_text: str):
    cleaned_source = clean_social_post_prompt(source_text) or source_text.strip()

    if client is None:
        return cleaned_source

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="""
You write concise Twitter posts.
Turn the user's topic into one ready-to-post tweet.
Keep it clear, natural, and engaging.
Return only the post text.
Do not use markdown.
Prefer staying under 280 characters.
""",
        input=cleaned_source,
    )

    return response.output_text.strip() or cleaned_source


def get_latest_twitter_post_reply():
    row = get_latest_social_post("twitter")

    if not row:
        return "You do not have any Twitter post draft yet, Misu."

    _post_id, _platform, _source_text, draft_text, _created_at = row
    return f"Here is your Twitter post, Misu. {draft_text}"


def extract_app_category_preference(user_text: str):
    text = user_text.strip()
    lowered = text.lower()

    if not any(
        phrase in lowered
        for phrase in [
            "mark ",
            "treat ",
            "set ",
            "consider ",
            "this app is",
            " is productive",
            " is distracting",
            " is neutral",
            " as productive",
            " as distracting",
            " as neutral",
        ]
    ):
        return None

    category = None

    if any(word in lowered for word in ["distracting", "disturbing", "distraction", "waste my time", "bad for me"]):
        category = "distracting"
    elif any(word in lowered for word in ["productive", "good for work", "work app", "focus app"]):
        category = "productive"
    elif "neutral" in lowered:
        category = "neutral"

    if not category:
        return None

    patterns = [
        r"\b(.+?)\s+is\s+(?:a\s+)?(?:distracting|disturbing|productive|neutral)",
        r"\bthis\s+app\s+(.+?)\s+is\s+(?:distracting|disturbing|productive|neutral)",
        r"\bmark\s+(.+?)\s+as\s+(?:a\s+)?(?:distracting|disturbing|productive|neutral)",
        r"\badd\s+(.+?)\s+as\s+(?:a\s+)?(?:distracting|disturbing|productive|neutral)",
    ]

    app_name = ""

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            app_name = match.group(1)
            break

    if not app_name:
        app_name = strip_command_words(
            text,
            [
                "this is",
                "this app is",
                "is",
                "a",
                "an",
                "disturbing",
                "distracting",
                "distraction",
                "productive",
                "neutral",
                "app",
                "for me",
                "please",
            ],
        )

    app_name = app_name.strip(" .,:;-")

    if not app_name or app_name.lower() in {"this", "this app"}:
        return None

    return app_name, category


def handle_pending_action(user_text: str):
    if pending_action["type"] == "add_reminder":
        time_match = TIME_PATTERN.search(user_text)

        if not time_match:
            return None

        reminder_time = time_match.group(0).strip()
        title_from_reply = TIME_PATTERN.sub(" ", user_text)
        title_from_reply = strip_command_words(
            title_from_reply,
            [
                "remember",
                "remember this",
                "remind",
                "remind me",
                "reminder",
                "this",
                "that",
                "i have",
                "i have a",
                "i have an",
                "about",
                "at",
                "on",
                "to",
                "please",
            ],
        )
        title = title_from_reply or pending_action["title"]

        if not title or title == "reminder":
            title = user_text

        reply = save_reminder_from_parts(title, reminder_time)

        if not reply:
            return None

        pending_action["type"] = ""
        pending_action["title"] = ""
        pending_action["platform"] = ""

        return reply

    if pending_action["type"] == "draft_social_post":
        client = get_openai_client()
        draft_text = build_twitter_post_draft(client, user_text)
        save_social_post(pending_action["platform"] or "twitter", user_text, draft_text)
        pending_action["type"] = ""
        pending_action["title"] = ""
        pending_action["platform"] = ""
        return f"Done, Misu. I drafted your Twitter post. Ask me for your Twitter post anytime."

    return None


def handle_local_actions(user_text: str):
    pending_reply = handle_pending_action(user_text)

    if pending_reply:
        return pending_reply

    if is_twitter_post_request(user_text):
        pending_action["type"] = "draft_social_post"
        pending_action["title"] = ""
        pending_action["platform"] = "twitter"
        return "Okay, Misu. Tell me what you want to post."

    if is_twitter_post_query(user_text):
        return get_latest_twitter_post_reply()

    done_work_entry = detect_done_work_entry(user_text)

    if done_work_entry:
        save_done_work(done_work_entry)
        return f"Okay, Misu. I saved {done_work_entry} in the things you have done."

    if is_done_work_query(user_text):
        return build_done_work_reply()

    client = get_openai_client()
    intent_data = detect_intent(client, user_text)

    intent = intent_data.get("intent", "general_chat")
    task = intent_data.get("task", "").strip()
    app_name = intent_data.get("app_name", "").strip()
    idea = intent_data.get("idea", "").strip()
    reminder_title = intent_data.get("reminder_title", "").strip()
    reminder_time = intent_data.get("reminder_time", "").strip()

    print("INTENT:", intent_data)

    if intent == "ask_usage":
        return build_local_usage_reply(user_text)

    if intent == "daily_report":
        return build_local_daily_report()

    if intent == "add_todo":
        if not task:
            if has_reminder_language(user_text.lower()):
                intent = "add_reminder"
            elif has_idea_language(user_text.lower()):
                intent = "save_idea"
                idea = idea or task or user_text
            else:
                return "Sure, Misu. Tell me the task you want me to add."

    if intent == "add_todo":
        add_todo(task)
        return f"Done, Misu. I added {task} to your list."

    if intent == "delete_todo":
        if not task:
            return "Sure, Misu. Which task should I remove?"

        if task.lower() in {"__all__", "both", "all", "everything", "entire list", "my list"}:
            deleted_titles = delete_all_todos()

            if not deleted_titles:
                return "Your todo list is already empty, Misu."

            if len(deleted_titles) == 1:
                return f"Done, Misu. I removed {deleted_titles[0]} from your todo list."

            if len(deleted_titles) == 2:
                deleted_text = " and ".join(deleted_titles)
            else:
                deleted_text = ", ".join(deleted_titles[:-1]) + f", and {deleted_titles[-1]}"

            return f"Done, Misu. I removed both tasks: {deleted_text}." if len(deleted_titles) == 2 else f"Done, Misu. I cleared {len(deleted_titles)} tasks from your todo list: {deleted_text}."

        deleted_title = delete_todo_by_text(task)

        if deleted_title:
            return f"Done, Misu. I removed {deleted_title} from your todo list."

        return f"I could not find {task} in your todo list, Misu. Want me to read the current tasks?"

    if intent == "complete_todo":
        if not task:
            return "Sure, which task is done?"

        if task.lower() in {"__current__", "this", "this task"}:
            completed_title = complete_single_pending_todo()

            if not completed_title:
                return "I need one clear task name, Misu. Which task did you finish?"
        else:
            completed_title = complete_todo_by_text(task)

        if completed_title:
            save_done_work(completed_title)
            return f"Nice, Misu. I marked {completed_title} as done."

        return f"I could not find {task}, Misu."

    if intent == "show_todos":
        if task == "__pending__":
            pending_text = get_pending_todos_text()
            return f"Here is what is pending, Misu. {pending_text}"

        if task == "__done__":
            done_text = get_done_todos_text()
            return f"Here is what is done, Misu. {done_text}"

        pending_text = get_pending_todos_text()
        done_text = get_done_todos_text()
        return f"Here is your todo list, Misu. Pending: {pending_text}. Done: {done_text}."

    if intent == "save_idea":
        if not idea:
            return "Sure, tell me the idea."

        save_idea(idea)
        return f"Nice, Misu. I saved that idea."

    if intent == "show_ideas":
        ideas_text = get_ideas_text()
        return f"Here are your saved ideas, Misu. {ideas_text}"

    if intent == "add_reminder":
        if not reminder_title:
            pending_action["type"] = "add_reminder"
            pending_action["title"] = ""
            return "Sure, what should I remind you about?"

        if not reminder_time:
            pending_action["type"] = "add_reminder"
            pending_action["title"] = reminder_title
            return f"Got it. When should I remind you about {reminder_title}?"

        reply = save_reminder_from_parts(reminder_title, reminder_time)

        if not reply:
            return f"I got the reminder, but missed the time. When should I remind you?"

        return reply

    if intent == "show_reminders":
        reminders_text = get_reminders_text()
        return f"Here are your reminders, Misu. {reminders_text}"

    app_preference = extract_app_category_preference(user_text)

    if app_preference:
        app_name, category = app_preference
        saved_app_name = set_app_category(app_name, category)

        if saved_app_name:
            spoken_category = "distracting" if category == "distracting" else category
            return f"Got it, Misu. I will treat {saved_app_name} as {spoken_category} from now."

    return None


def remember_conversation(user_text: str, reply: str):
    conversation_memory.append(
        {
            "user": user_text.strip(),
            "vexa": reply.strip(),
        }
    )

    del conversation_memory[:-8]


def get_conversation_memory_text():
    if not conversation_memory:
        return "No recent conversation yet."

    lines = []

    for item in conversation_memory[-8:]:
        lines.append(f"Misu: {item['user']}")
        lines.append(f"Vexa: {item['vexa']}")

    return "\n".join(lines)


def build_general_reply(client, user_text: str):
    now = datetime.now()
    usage_text = get_today_usage_text()
    yesterday_usage_text = get_usage_text_for_date(get_yesterday_date())
    productivity_text = get_productivity_summary_text()
    comparison_text = get_daily_comparison_text()
    todos_text = get_todos_text()
    pending_todos_text = get_pending_todos_text()
    done_todos_text = get_done_todos_text()
    ideas_text = get_ideas_text()
    reminders_text = get_reminders_text()
    app_preferences_text = get_app_preferences_text()
    memory_text = get_conversation_memory_text()

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, Misu's voice-first AI companion.
You can help with productivity, but you are also good at normal human conversation.
{FRIENDLY_VOICE_STYLE}

Current date and time:
{now.strftime("%A, %B %d, %Y at %I:%M %p")}

Recent conversation:
{memory_text}

Today's app usage data:
{usage_text}

Yesterday's app usage data:
{yesterday_usage_text}

Productivity summary:
{productivity_text}

Comparison:
{comparison_text}

Current todo list:
{todos_text}

Pending tasks:
{pending_todos_text}

Completed tasks:
{done_todos_text}

Saved ideas:
{ideas_text}

Upcoming reminders:
{reminders_text}

Custom app preferences:
{app_preferences_text}

Behavior:
- If Misu is casually talking, respond conversationally and emotionally aware.
- If Misu talks about his day, ask or say something that naturally continues the conversation.
- If Misu wants to discuss an idea, say yes naturally and help him think it through instead of saving it unless he explicitly asks to save it.
- If Misu asks what he did today or how he spent time, use tracked app usage and ask about the human side of his day.
- If Misu says he wants to talk for a while, say yes warmly and invite him to tell you what's on his mind.
- If Misu asks about app usage, distraction, productivity, todos, pending tasks, completed tasks, ideas, or reminders, use the data above.
- If Misu asks about yesterday, use the comparison data and yesterday values.
- If Misu asks for a report, summarize today or yesterday clearly with productive time, distracting time, top apps, tasks, and reminders.
- Do not mention internal data unless it is relevant to what Misu asked.
- Do not say you cannot have a normal conversation.
- Sound like one intelligent, friendly person speaking, not a command parser.
""",
        input=user_text,
    )

    reply = response.output_text.strip()
    remember_conversation(user_text, reply)
    return reply


@app.post("/chat")
def chat(request: ChatRequest):
    local_reply = handle_local_actions(request.message)

    if local_reply:
        remember_conversation(request.message, local_reply)
        return {"reply": local_reply}

    client = get_openai_client()

    if client is None:
        return missing_api_key_reply()

    return {"reply": build_general_reply(client, request.message)}


@app.post("/voice-command")
def voice_command():
    client = get_openai_client()

    if client is None:
        return {
            "transcript": "",
            **missing_api_key_reply(),
        }

    try:
        audio_file = record_audio(duration=VOICE_RECORD_SECONDS)
    except Exception as error:
        print("VOICE_RECORDING_ERROR:", repr(error))
        raise HTTPException(
            status_code=503,
            detail="Microphone recording failed. Allow microphone access for Vexa and restart the app.",
        ) from error

    try:
        with open(audio_file, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en",
                prompt=VOICE_TRANSCRIPTION_PROMPT,
            )
    except Exception as error:
        print("VOICE_TRANSCRIPTION_ERROR:", repr(error))
        raise HTTPException(
            status_code=502,
            detail="Vexa recorded audio but could not transcribe it. Check the OpenAI API key and network.",
        ) from error

    user_text = transcription.text.strip()

    try:
        return build_voice_reply(client, user_text)
    except Exception as error:
        print("VOICE_REPLY_ERROR:", repr(error))
        raise HTTPException(
            status_code=502,
            detail="Vexa heard you but could not generate a reply. Check the OpenAI API key and network.",
        ) from error


@app.post("/voice-command-audio")
async def voice_command_audio(file: UploadFile = File(...)):
    client = get_openai_client()

    if client is None:
        return {
            "transcript": "",
            **missing_api_key_reply(),
        }

    uploaded_audio = await file.read()

    if not uploaded_audio:
        raise HTTPException(
            status_code=400,
            detail="No audio was recorded. Check microphone permission and try again.",
        )

    suffix = Path(file.filename or "voice.webm").suffix or ".webm"

    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(uploaded_audio)

    try:
        try:
            with temp_path.open("rb") as f:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="en",
                    prompt=VOICE_TRANSCRIPTION_PROMPT,
                )
        except Exception as error:
            print("VOICE_UPLOAD_TRANSCRIPTION_ERROR:", repr(error))
            raise HTTPException(
                status_code=502,
                detail="Vexa received audio but could not transcribe it. Check the OpenAI API key and network.",
            ) from error
    finally:
        temp_path.unlink(missing_ok=True)

    user_text = transcription.text.strip()

    try:
        return build_voice_reply(client, user_text)
    except Exception as error:
        print("VOICE_UPLOAD_REPLY_ERROR:", repr(error))
        raise HTTPException(
            status_code=502,
            detail="Vexa heard you but could not generate a reply. Check the OpenAI API key and network.",
        ) from error


def build_voice_reply(client, user_text: str):
    print("TRANSCRIPT:", user_text)

    if not user_text:
        return {
            "transcript": user_text,
            "reply": "I didn't catch that, Misu. Say it again?",
        }

    local_reply = handle_local_actions(user_text)

    if local_reply:
        remember_conversation(user_text, local_reply)
        return {
            "transcript": user_text,
            "reply": local_reply,
        }

    reply = build_general_reply(client, user_text)

    return {
        "transcript": user_text,
        "reply": reply,
    }


@app.get("/today-usage")
def today_usage():
    try:
        rows = get_usage_rows()

        return {
            "date": today_date().isoformat(),
            "window": "today",
            "usage": rows_to_usage_items(rows),
        }

    except Exception as e:
        return {"error": str(e)}


@app.get("/productivity-summary")
def productivity_summary():
    try:
        return {
            "date": today_date().isoformat(),
            "window": "today",
            "summary": get_productivity_summary_text(),
            "comparison": get_daily_comparison(),
        }

    except Exception as e:
        return {"error": str(e)}


@app.get("/focus-alert")
def focus_alert():
    try:
        return get_focus_alert_for_latest_app()

    except Exception as e:
        return {"alert": False, "error": str(e)}


@app.get("/usage-comparison")
def usage_comparison():
    try:
        yesterday = get_yesterday_date()

        return {
            "today_date": today_date().isoformat(),
            "yesterday_date": yesterday.isoformat(),
            "today_usage": rows_to_usage_items(get_usage_rows_for_date(today_date())),
            "yesterday_usage": rows_to_usage_items(get_usage_rows_for_date(yesterday)),
            "comparison": get_daily_comparison(),
        }

    except Exception as e:
        return {"error": str(e)}


@app.get("/todos")
def todos():
    try:
        todos_text = get_todos_text()
        return {"todos": todos_text}

    except Exception as e:
        return {"error": str(e)}


@app.get("/ideas")
def ideas():
    try:
        ideas_text = get_ideas_text()
        return {"ideas": ideas_text}

    except Exception as e:
        return {"error": str(e)}


@app.get("/reminders")
def reminders():
    try:
        reminders_text = get_reminders_text()
        return {"reminders": reminders_text}

    except Exception as e:
        return {"error": str(e)}


@app.get("/reminders/due")
def due_reminders():
    try:
        return {"reminders": pop_due_reminders()}

    except Exception as e:
        return {"error": str(e)}


@app.get("/dashboard")
def dashboard():
    try:
        rows = get_usage_rows()
        usage_items = rows_to_usage_items(rows)
        yesterday_usage_items = rows_to_usage_items(get_usage_rows_for_date(get_yesterday_date()))
        comparison = get_daily_comparison()
        day_start = datetime.combine(today_date(), datetime.min.time())
        day_end = day_start + timedelta(days=1)

        return {
            "date": today_date().isoformat(),
            "window": "today",
            "day_start": day_start.isoformat(),
            "day_end": day_end.isoformat(),
            "totals": comparison["today"],
            "yesterday_totals": comparison["yesterday"],
            "comparison": comparison,
            "top_apps_today": usage_items[:5],
            "top_apps_yesterday": yesterday_usage_items[:5],
            "top_apps": usage_items[:5],
            "todos": get_todos_text(),
            "ideas": get_ideas_text(),
            "reminders": get_reminders_text(),
        }

    except Exception as e:
        return {"error": str(e)}
