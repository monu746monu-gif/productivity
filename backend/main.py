import os
import sqlite3
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel

from recorder import record_audio

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


@app.post("/chat")
def chat(request: ChatRequest):
    today_usage = get_today_usage_text()

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly AI productivity companion.
The user's name is Monu.

Today's app usage data:
{today_usage}

If the user asks about app usage, work time, productivity, Cursor, Chrome, Terminal, or focus time,
answer using today's app usage data.
Keep replies short and natural because they will be spoken aloud.
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

    today_usage = get_today_usage_text()
    print("TODAY USAGE:", today_usage)

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly AI productivity companion.
The user's name is Monu.

Today's app usage data:
{today_usage}

If the user asks about Cursor, Chrome, Terminal, productivity time, work time, focus time, or app usage,
answer directly using this data.

Do not say you do not have access to usage data.
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