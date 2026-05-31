import os
import sqlite3
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from recorder import record_audio
from todos import add_todo, get_todos_text, delete_todo_by_text, complete_todo_by_text

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/")
def health_check():
    return {"status": "Vexa backend is running"}


def get_today_usage_text():
    conn = sqlite3.connect("vexa.db", timeout=1)
    cursor = conn.cursor()

    today = datetime.now().date().isoformat()

    cursor.execute(
        """
        SELECT app_name, COUNT(*) as count
        FROM app_usage
        WHERE DATE(timestamp) = ?
        GROUP BY app_name
        ORDER BY count DESC
        """,
        (today,),
    )

    rows = cursor.fetchall()
    conn.close()

    interval_seconds = 5

    if not rows:
        return "No app usage data has been tracked today."

    usage_lines = []

    for app_name, count in rows:
        seconds = count * interval_seconds
        minutes = round(seconds / 60, 2)
        usage_lines.append(f"{app_name}: {minutes} minutes")

    return "\n".join(usage_lines)


def handle_local_actions(user_text: str):
    text = user_text.lower().strip()

    # Show todos
    show_todo_phrases = [
        "show my todo",
        "show todos",
        "what are my tasks",
        "my todo list",
        "what is my todo",
        "what's my todo",
        "show my tasks",
        "tell my tasks",
        "tell me my tasks",
    ]

    if any(phrase in text for phrase in show_todo_phrases):
        todos_text = get_todos_text()
        return f"Here are your current tasks. {todos_text}"

    # Delete / remove todo
    delete_words = ["delete", "remove", "clear"]
    todo_words = ["todo", "to do", "task", "checklist"]

    if any(word in text for word in delete_words) and any(word in text for word in todo_words):
        task = user_text

        remove_phrases = [
            "delete",
            "remove",
            "clear",
            "from my todo list",
            "from todo list",
            "from my to do list",
            "to do list",
            "todo list",
            "todo",
            "task",
            "checklist",
        ]

        for phrase in remove_phrases:
            task = task.replace(phrase, "")
            task = task.replace(phrase.title(), "")

        task = task.strip(" .")

        deleted_title = delete_todo_by_text(task)

        if deleted_title:
            return f"Done Monu, I removed {deleted_title} from your todo list."

        return f"I could not find {task} in your todo list."

    # Mark todo as complete
    complete_words = ["complete", "done", "finished", "mark"]
    complete_phrases = ["mark as done", "mark it done", "mark complete", "completed"]

    if any(word in text for word in complete_words) or any(phrase in text for phrase in complete_phrases):
        task = user_text

        remove_phrases = [
            "complete",
            "done",
            "finished",
            "mark",
            "mark as done",
            "mark it done",
            "mark complete",
            "completed",
            "my todo",
            "todo",
            "task",
            "checklist",
            "to do",
        ]

        for phrase in remove_phrases:
            task = task.replace(phrase, "")
            task = task.replace(phrase.title(), "")

        task = task.strip(" .")

        completed_title = complete_todo_by_text(task)

        if completed_title:
            return f"Nice Monu, I marked {completed_title} as done."

        return f"I could not find {task} in your todo list."

    # Add todo
    add_words = ["add", "create", "save", "make", "put"]

    if any(word in text for word in add_words) and any(word in text for word in todo_words):
        task = user_text

        remove_phrases = [
            "add",
            "create",
            "save",
            "make",
            "put",
            "to my todo list",
            "to todo list",
            "to my to do list",
            "to do list",
            "todo list",
            "todo",
            "task",
            "checklist",
        ]

        for phrase in remove_phrases:
            task = task.replace(phrase, "")
            task = task.replace(phrase.title(), "")

        task = task.strip(" .")

        if not task:
            task = user_text

        add_todo(task)

        return f"Done Monu, I added {task} to your todo list."

    return None
 

@app.post("/chat")
def chat(request: ChatRequest):
    local_reply = handle_local_actions(request.message)

    if local_reply:
        return {
            "reply": local_reply,
        }

    today_usage = get_today_usage_text()
    todos_text = get_todos_text()

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly AI productivity companion.
The user's name is Monu.

Today's app usage data:
{today_usage}

Current todo list:
{todos_text}

If the user asks about app usage, work time, productivity, Cursor, Chrome, Terminal, or focus time,
answer using today's app usage data.

If the user asks about todos or tasks, answer using the current todo list.

Keep replies short and natural because they will be spoken aloud.
Do not say you do not have access to usage data or todos.
""",
        input=request.message,
    )

    return {
        "reply": response.output_text,
    }


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
                "productivity, todo, checklist, app usage, and work time."
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

    today_usage = get_today_usage_text()
    todos_text = get_todos_text()

    print("TODAY USAGE:", today_usage)
    print("TODOS:", todos_text)

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly voice-first AI productivity companion.
The user's name is Monu.

Today's app usage data:
{today_usage}

Current todo list:
{todos_text}

If the user asks about Cursor, Chrome, Terminal, productivity time, work time, focus time, or app usage,
answer directly using today's data.

If the user asks about todos or tasks, answer using the current todo list.

Do not say you do not have access to usage data or todos.
Keep replies short and natural because they will be spoken aloud.
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
        conn = sqlite3.connect("vexa.db", timeout=1)
        cursor = conn.cursor()

        today = datetime.now().date().isoformat()

        cursor.execute(
            """
            SELECT app_name, COUNT(*) as count
            FROM app_usage
            WHERE DATE(timestamp) = ?
            GROUP BY app_name
            ORDER BY count DESC
            """,
            (today,),
        )

        rows = cursor.fetchall()
        conn.close()

        interval_seconds = 5
        usage = []

        for app_name, count in rows:
            seconds = count * interval_seconds
            minutes = round(seconds / 60, 2)

            usage.append(
                {
                    "app_name": app_name,
                    "seconds": seconds,
                    "minutes": minutes,
                }
            )

        return {
            "date": today,
            "usage": usage,
        }

    except Exception as e:
        return {
            "error": str(e),
        }


@app.get("/todos")
def todos():
    try:
        todos_text = get_todos_text()

        return {
            "todos": todos_text,
        }

    except Exception as e:
        return {
            "error": str(e),
        }
