import os
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from intent import detect_intent
from productivity import classify_app
from recorder import record_audio
from todos import (
    add_todo,
    get_todos_text,
    delete_todo_by_text,
    complete_todo_by_text,
)

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
USAGE_WINDOW_HOURS = 20


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def health_check():
    return {"status": "Vexa backend is running"}


def get_usage_rows():
    conn = sqlite3.connect("vexa.db", timeout=1)
    cursor = conn.cursor()

    start_time = (datetime.now() - timedelta(hours=USAGE_WINDOW_HOURS)).isoformat()

    cursor.execute(
        """
        SELECT app_name, COUNT(*) as count
        FROM app_usage
        WHERE timestamp >= ?
        GROUP BY app_name
        ORDER BY count DESC
        """,
        (start_time,),
    )

    rows = cursor.fetchall()
    conn.close()

    return rows


def get_today_usage_text():
    rows = get_usage_rows()

    if not rows:
        return f"No app usage data has been tracked in the last {USAGE_WINDOW_HOURS} hours."

    usage_lines = []

    for app_name, count in rows:
        seconds = count * TRACKER_INTERVAL_SECONDS
        minutes = round(seconds / 60, 2)
        usage_lines.append(f"{app_name}: {minutes} minutes")

    return "\n".join(usage_lines)


def get_productivity_summary_text():
    rows = get_usage_rows()

    if not rows:
        return f"No productivity data has been tracked in the last {USAGE_WINDOW_HOURS} hours."

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
Productivity summary from the last {USAGE_WINDOW_HOURS} hours:
Productive time: {productive} minutes
Neutral time: {neutral} minutes
Distracting time: {distracting} minutes

App breakdown:
{chr(10).join(app_lines)}
"""


def handle_local_actions(user_text: str):
    intent_data = detect_intent(client, user_text)

    intent = intent_data.get("intent", "general_chat")
    task = intent_data.get("task", "").strip()
    app_name = intent_data.get("app_name", "").strip()

    print("INTENT:", intent_data)

    if intent == "add_todo":
        if not task:
            return "What task should I add, Monu?"

        add_todo(task)
        return f"Done Monu, I added {task} to your todo list."

    if intent == "delete_todo":
        if not task:
            return "Which task should I remove, Monu?"

        deleted_title = delete_todo_by_text(task)

        if deleted_title:
            return f"Done Monu, I removed {deleted_title} from your todo list."

        return f"I could not find {task} in your todo list."

    if intent == "complete_todo":
        if not task:
            return "Which task should I mark as done, Monu?"

        completed_title = complete_todo_by_text(task)

        if completed_title:
            return f"Nice Monu, I marked {completed_title} as done."

        return f"I could not find {task} in your todo list."

    if intent == "show_todos":
        todos_text = get_todos_text()
        return f"Here are your current tasks. {todos_text}"

    if intent == "ask_usage":
        usage_text = get_today_usage_text()
        productivity_text = get_productivity_summary_text()

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=f"""
You are Vexa, a voice-first productivity assistant.
The user's name is Monu.

App usage data from the last {USAGE_WINDOW_HOURS} hours:
{usage_text}

Productivity summary:
{productivity_text}

The user is asking about usage or productivity.
Answer directly using the data.
Keep it short and spoken-friendly.
Do not say you do not have access to usage data.
""",
            input=user_text,
        )

        return response.output_text

    if intent == "daily_report":
        usage_text = get_today_usage_text()
        productivity_text = get_productivity_summary_text()
        todos_text = get_todos_text()

        response = client.responses.create(
            model="gpt-4.1-mini",
            instructions=f"""
You are Vexa, a voice-first productivity assistant.
The user's name is Monu.

App usage data from the last {USAGE_WINDOW_HOURS} hours:
{usage_text}

Productivity summary:
{productivity_text}

Current todo list:
{todos_text}

Create a short spoken daily productivity report.
Include:
1. productive time
2. distracting time
3. top used apps
4. pending tasks
5. one improvement suggestion

Keep it natural, friendly, and under 6 sentences.
Do not say you do not have access to usage data or todos.
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

    usage_text = get_today_usage_text()
    productivity_text = get_productivity_summary_text()
    todos_text = get_todos_text()

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly AI productivity companion.
The user's name is Monu.

App usage data from the last {USAGE_WINDOW_HOURS} hours:
{usage_text}

Productivity summary:
{productivity_text}

Current todo list:
{todos_text}

If the user asks about app usage, work time, productivity, Cursor, Chrome, Terminal, or focus time,
answer using the app usage data and productivity summary.

If the user asks about todos or tasks, answer using the current todo list.

Keep replies short, natural, and spoken-friendly.
Do not say you do not have access to usage data or todos.
""",
        input=request.message,
    )

    return {"reply": response.output_text}


@app.post("/voice-command")
def voice_command():
    audio_file = record_audio(duration=8)

    with open(audio_file, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="en",
            prompt=(
                "The user is speaking English or Hinglish to an AI productivity "
                "assistant named Vexa. Terms may include Cursor, Chrome, Terminal, "
                "productivity, todo, checklist, app usage, work time, delete task, "
                "remove task, mark task done, daily report, and productivity summary."
            ),
        )

    user_text = transcription.text
    print("TRANSCRIPT:", user_text)

    local_reply = handle_local_actions(user_text)

    if local_reply:
        return {
            "transcript": user_text,
            "reply": local_reply,
        }

    usage_text = get_today_usage_text()
    productivity_text = get_productivity_summary_text()
    todos_text = get_todos_text()

    print("USAGE:", usage_text)
    print("PRODUCTIVITY:", productivity_text)
    print("TODOS:", todos_text)

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly voice-first AI productivity companion.
The user's name is Monu.

App usage data from the last {USAGE_WINDOW_HOURS} hours:
{usage_text}

Productivity summary:
{productivity_text}

Current todo list:
{todos_text}

If the user asks about Cursor, Chrome, Terminal, productivity time, work time, focus time, or app usage,
answer directly using the app usage data and productivity summary.

If the user asks about todos or tasks, answer using the current todo list.

If the user asks for a daily report, summarize productivity, top apps, pending tasks, and one improvement suggestion.

Do not say you do not have access to usage data or todos.
Keep replies short, natural, and spoken-friendly.
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

        return {
            "window": f"last_{USAGE_WINDOW_HOURS}_hours",
            "usage": usage,
        }

    except Exception as e:
        return {"error": str(e)}


@app.get("/productivity-summary")
def productivity_summary():
    try:
        return {
            "window": f"last_{USAGE_WINDOW_HOURS}_hours",
            "summary": get_productivity_summary_text(),
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


@app.get("/dashboard")
def dashboard():
    try:
        rows = get_usage_rows()
        todos_text = get_todos_text()

        totals = {
            "productive": 0,
            "neutral": 0,
            "distracting": 0,
        }

        top_apps = []

        for app_name, count in rows:
            seconds = count * TRACKER_INTERVAL_SECONDS
            minutes = round(seconds / 60, 2)
            category = classify_app(app_name)

            totals[category] += minutes

            top_apps.append(
                {
                    "app_name": app_name,
                    "minutes": minutes,
                    "category": category,
                }
            )

        return {
            "window": f"last_{USAGE_WINDOW_HOURS}_hours",
            "totals": {
                "productive": round(totals["productive"], 2),
                "neutral": round(totals["neutral"], 2),
                "distracting": round(totals["distracting"], 2),
            },
            "top_apps": top_apps[:5],
            "todos": todos_text,
        }

    except Exception as e:
        return {"error": str(e)}    