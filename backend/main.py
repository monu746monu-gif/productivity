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
    has_idea_language,
    has_reminder_language,
    has_todo_language,
    strip_command_words,
)
from ideas import save_idea, get_ideas_text
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
}

conversation_memory = []
last_focus_alerts = {}


FRIENDLY_VOICE_STYLE = """
Conversation style:
- Talk like a real person who is present with Monu, not like a formal report.
- Keep voice replies short, warm, and natural: usually 1 to 3 sentences.
- If Monu shares his day, mood, plans, time, or random thoughts, respond like a thoughtful friend.
- Ask one gentle follow-up question when it would keep the conversation flowing.
- For casual chat, do not turn the answer into productivity advice unless Monu asks for it.
- Use simple words, natural spoken rhythm, and light Hinglish only when it fits.
- If Monu says he wants to talk for some time, settle into conversation and invite him to continue.
- Do not over-explain.
- Do not use markdown, numbered lists, or long paragraphs in voice replies.
"""


VOICE_TRANSCRIPTION_PROMPT = (
    "The user is speaking English or Hinglish to an AI productivity "
    "assistant named Vexa. Terms may include Cursor, Chrome, Terminal, "
    "productivity, todo, checklist, app usage, work time, delete task, "
    "remove task, mark task done, daily report, productivity summary, "
    "save idea, remember idea, meeting, call, and reminder."
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
        f"Monu, nooo. You marked {app_name} as distracting. "
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


def save_reminder_from_parts(title: str, reminder_time: str):
    remind_at = parse_reminder_time(reminder_time)

    if not remind_at:
        return None

    add_reminder(title, remind_at.isoformat())
    spoken_time = remind_at.strftime("%I:%M %p").lstrip("0")
    return f"Done, Monu. I will remind you about {title} at {spoken_time}."


def extract_app_category_preference(user_text: str):
    text = user_text.strip()
    lowered = text.lower()

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
    if pending_action["type"] != "add_reminder":
        return None

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

    return reply


def handle_local_actions(user_text: str):
    pending_reply = handle_pending_action(user_text)

    if pending_reply:
        return pending_reply

    app_preference = extract_app_category_preference(user_text)

    if app_preference:
        app_name, category = app_preference
        saved_app_name = set_app_category(app_name, category)

        if saved_app_name:
            spoken_category = "distracting" if category == "distracting" else category
            return f"Got it, Monu. I will treat {saved_app_name} as {spoken_category} from now."

    client = get_openai_client()
    intent_data = detect_intent(client, user_text)

    intent = intent_data.get("intent", "general_chat")
    task = intent_data.get("task", "").strip()
    app_name = intent_data.get("app_name", "").strip()
    idea = intent_data.get("idea", "").strip()
    reminder_title = intent_data.get("reminder_title", "").strip()
    reminder_time = intent_data.get("reminder_time", "").strip()

    print("INTENT:", intent_data)

    if intent == "add_todo":
        if not has_todo_language(user_text.lower()):
            if has_reminder_language(user_text.lower()):
                intent = "add_reminder"
            elif has_idea_language(user_text.lower()):
                intent = "save_idea"
                idea = idea or task or user_text
            else:
                return "Got it, Monu. Should I save that as an idea or make it a todo?"

    if intent == "add_todo":
        if not task:
            return "Sure, Monu. Tell me the tasks you want on the list, one by one or in one sentence."

        add_todo(task)
        return f"Done, Monu. I added {task} to your list."

    if intent == "delete_todo":
        if not task:
            return "Sure, Monu. Which task should I remove?"

        if task.lower() in {"__all__", "both", "all", "everything", "entire list", "my list"}:
            deleted_titles = delete_all_todos()

            if not deleted_titles:
                return "Your todo list is already empty, Monu."

            if len(deleted_titles) == 1:
                return f"Done, Monu. I removed {deleted_titles[0]} from your todo list."

            if len(deleted_titles) == 2:
                deleted_text = " and ".join(deleted_titles)
            else:
                deleted_text = ", ".join(deleted_titles[:-1]) + f", and {deleted_titles[-1]}"

            return f"Done, Monu. I removed both tasks: {deleted_text}." if len(deleted_titles) == 2 else f"Done, Monu. I cleared {len(deleted_titles)} tasks from your todo list: {deleted_text}."

        deleted_title = delete_todo_by_text(task)

        if deleted_title:
            return f"Done, Monu. I removed {deleted_title} from your todo list."

        return f"I could not find {task} in your todo list, Monu. Want me to read the current tasks?"

    if intent == "complete_todo":
        if not task:
            return "Sure, which task is done?"

        if task.lower() in {"__current__", "this", "this task"}:
            completed_title = complete_single_pending_todo()

            if not completed_title:
                return "I need one clear task name, Monu. Which task did you finish?"
        else:
            completed_title = complete_todo_by_text(task)

        if completed_title:
            return f"Nice, Monu. I marked {completed_title} as done."

        return f"I could not find {task}, Monu."

    if intent == "show_todos":
        if task == "__pending__":
            pending_text = get_pending_todos_text()
            return f"Here is what is pending, Monu. {pending_text}"

        if task == "__done__":
            done_text = get_done_todos_text()
            return f"Here is what is done, Monu. {done_text}"

        pending_text = get_pending_todos_text()
        done_text = get_done_todos_text()
        return f"Here is your todo list, Monu. Pending: {pending_text}. Done: {done_text}."

    if intent == "save_idea":
        if not idea:
            return "Sure, tell me the idea."

        save_idea(idea)
        return f"Nice, Monu. I saved that idea."

    if intent == "show_ideas":
        ideas_text = get_ideas_text()
        return f"Here are your saved ideas, Monu. {ideas_text}"

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
        return f"Here are your reminders, Monu. {reminders_text}"

    if intent == "ask_usage":
        client = get_openai_client()

        if client is None:
            return "Vexa is not configured with the server OpenAI API key yet."

        usage_text = get_today_usage_text()
        productivity_text = get_productivity_summary_text()
        comparison_text = get_daily_comparison_text()

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=f"""
You are Vexa, a voice-first productivity assistant.
The user's name is Monu.
{FRIENDLY_VOICE_STYLE}

Today's app usage data:
{usage_text}

Productivity summary:
{productivity_text}

Comparison:
{comparison_text}

The user is asking about usage or productivity.
Answer directly using today's data. If they ask about yesterday or comparison, use the comparison data.
Do not say you do not have access to usage data.
""",
            input=user_text,
        )

        return response.output_text

    if intent == "daily_report":
        client = get_openai_client()

        if client is None:
            return "Vexa is not configured with the server OpenAI API key yet."

        usage_text = get_today_usage_text()
        productivity_text = get_productivity_summary_text()
        comparison_text = get_daily_comparison_text()
        todos_text = get_todos_text()
        ideas_text = get_ideas_text()
        reminders_text = get_reminders_text()

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=f"""
You are Vexa, a voice-first productivity assistant.
The user's name is Monu.
{FRIENDLY_VOICE_STYLE}

Today's app usage data:
{usage_text}

Productivity summary:
{productivity_text}

Comparison:
{comparison_text}

Current todo list:
{todos_text}

Saved ideas:
{ideas_text}

Upcoming reminders:
{reminders_text}

Create a short spoken daily productivity report.
Include:
1. productive time
2. distracting time
3. top used apps
4. pending tasks
5. one improvement suggestion

Keep it natural, friendly, and under 6 sentences.
Do not say you do not have access to usage data, todos, ideas, or reminders.
""",
            input=user_text,
        )

        return response.output_text

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
        lines.append(f"Monu: {item['user']}")
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
You are Vexa, Monu's voice-first AI companion.
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
- If Monu is casually talking, respond conversationally and emotionally aware.
- If Monu talks about his day, ask or say something that naturally continues the conversation.
- If Monu asks what he did today or how he spent time, use tracked app usage and ask about the human side of his day.
- If Monu says he wants to talk for a while, say yes warmly and invite him to tell you what's on his mind.
- If Monu asks about app usage, distraction, productivity, todos, pending tasks, completed tasks, ideas, or reminders, use the data above.
- If Monu asks about yesterday, use the comparison data and yesterday values.
- If Monu asks for a report, summarize today or yesterday clearly with productive time, distracting time, top apps, tasks, and reminders.
- Do not mention internal data unless it is relevant to what Monu asked.
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
            "reply": "I didn't catch that, Monu. Say it again?",
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
