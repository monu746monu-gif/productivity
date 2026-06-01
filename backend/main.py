import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from storage import get_db_path

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
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
    save_openai_api_key,
)
from todos import (
    add_todo,
    get_todos_text,
    delete_todo_by_text,
    complete_todo_by_text,
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
VOICE_RECORD_SECONDS = 4


class ChatRequest(BaseModel):
    message: str


class ApiKeyRequest(BaseModel):
    api_key: str


pending_action = {
    "type": "",
    "title": "",
}


FRIENDLY_VOICE_STYLE = """
Conversation style:
- Talk like a warm, friendly assistant, not a formal report.
- Keep normal replies to 1 or 2 short sentences.
- Use simple words and a natural spoken rhythm.
- If the request is unclear, ask one quick follow-up question.
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
        "reply": "Add your OpenAI API key in settings first, then I can listen and chat.",
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
    if is_openai_api_key_managed():
        return {
            "saved": False,
            "error": "This backend is already configured by Vexa.",
            "openai_api_key_configured": True,
            "openai_api_key_managed": True,
        }

    api_key = request.api_key.strip()

    if not api_key:
        return {
            "saved": False,
            "error": "API key is required.",
        }

    save_openai_api_key(api_key)

    return {
        "saved": True,
        "openai_api_key_configured": True,
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
    rows = get_usage_rows()

    if not rows:
        return "No app usage data has been tracked today."

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
            return "Sure, what task should I add?"

        add_todo(task)
        return f"Done, Monu. I added {task} to your list."

    if intent == "delete_todo":
        if not task:
            return "Sure, which task should I remove?"

        deleted_title = delete_todo_by_text(task)

        if deleted_title:
            return f"Done, I removed {deleted_title}."

        return f"I could not find {task}, Monu."

    if intent == "complete_todo":
        if not task:
            return "Sure, which task is done?"

        completed_title = complete_todo_by_text(task)

        if completed_title:
            return f"Nice, Monu. I marked {completed_title} as done."

        return f"I could not find {task}, Monu."

    if intent == "show_todos":
        todos_text = get_todos_text()
        return f"Here are your tasks, Monu. {todos_text}"

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
            return "Add your OpenAI API key in settings first, then I can answer that."

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
            return "Add your OpenAI API key in settings first, then I can make your report."

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


@app.post("/chat")
def chat(request: ChatRequest):
    local_reply = handle_local_actions(request.message)

    if local_reply:
        return {"reply": local_reply}

    client = get_openai_client()

    if client is None:
        return missing_api_key_reply()

    usage_text = get_today_usage_text()
    productivity_text = get_productivity_summary_text()
    comparison_text = get_daily_comparison_text()
    todos_text = get_todos_text()
    ideas_text = get_ideas_text()
    reminders_text = get_reminders_text()

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly AI productivity companion.
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

If the user asks about app usage, work time, productivity, Cursor, Chrome, Terminal, or focus time,
answer using the app usage data and productivity summary.

If the user asks about yesterday or comparing today and yesterday, answer using the comparison data.

If the user asks about todos or tasks, answer using the current todo list.

If the user asks about saved ideas, answer using saved ideas.

If the user asks about reminders, calls, meetings, or scheduled things, answer using upcoming reminders.

Do not say you do not have access to usage data, todos, ideas, or reminders.
""",
        input=request.message,
    )

    return {"reply": response.output_text}


@app.post("/voice-command")
def voice_command():
    client = get_openai_client()

    if client is None:
        return {
            "transcript": "",
            **missing_api_key_reply(),
        }

    audio_file = record_audio(duration=VOICE_RECORD_SECONDS)

    with open(audio_file, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="en",
            prompt=VOICE_TRANSCRIPTION_PROMPT,
        )

    user_text = transcription.text.strip()
    return build_voice_reply(client, user_text)


@app.post("/voice-command-audio")
async def voice_command_audio(file: UploadFile = File(...)):
    client = get_openai_client()

    if client is None:
        return {
            "transcript": "",
            **missing_api_key_reply(),
        }

    suffix = Path(file.filename or "voice.webm").suffix or ".webm"

    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(await file.read())

    try:
        with temp_path.open("rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="en",
                prompt=VOICE_TRANSCRIPTION_PROMPT,
            )
    finally:
        temp_path.unlink(missing_ok=True)

    user_text = transcription.text.strip()
    return build_voice_reply(client, user_text)


def build_voice_reply(client, user_text: str):
    print("TRANSCRIPT:", user_text)

    if not user_text:
        return {
            "transcript": user_text,
            "reply": "I didn't catch that, Monu. Say it again?",
        }

    local_reply = handle_local_actions(user_text)

    if local_reply:
        return {
            "transcript": user_text,
            "reply": local_reply,
        }

    usage_text = get_today_usage_text()
    productivity_text = get_productivity_summary_text()
    comparison_text = get_daily_comparison_text()
    todos_text = get_todos_text()
    ideas_text = get_ideas_text()
    reminders_text = get_reminders_text()

    print("USAGE:", usage_text)
    print("PRODUCTIVITY:", productivity_text)
    print("TODOS:", todos_text)
    print("IDEAS:", ideas_text)
    print("REMINDERS:", reminders_text)

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly voice-first AI productivity companion.
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

If the user asks about Cursor, Chrome, Terminal, productivity time, work time, focus time, or app usage,
answer directly using the app usage data and productivity summary.

If the user asks about yesterday or comparing today and yesterday, answer using the comparison data.

If the user asks about todos or tasks, answer using the current todo list.

If the user asks about saved ideas, answer using saved ideas.

If the user asks about reminders, calls, meetings, or scheduled things, answer using upcoming reminders.

If the user asks for a daily report, summarize productivity, top apps, pending tasks, saved ideas, reminders, and one improvement suggestion.

Do not say you do not have access to usage data, todos, ideas, or reminders.
""",
        input=user_text,
    )

    return {
        "transcript": user_text,
        "reply": response.output_text,
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
