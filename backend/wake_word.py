import os
import subprocess
import time
import sqlite3
from datetime import datetime
from todos import add_todo, get_todos_text
from dotenv import load_dotenv
from openai import OpenAI

from recorder import record_audio

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def speak(text: str):
    subprocess.run(["say", text])


def transcribe_audio(audio_file: str, prompt: str = ""):
    with open(audio_file, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="en",
            prompt=prompt,
        )

    return transcription.text


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
        minutes = round((count * interval_seconds) / 60, 2)
        usage_lines.append(f"{app_name}: {minutes} minutes")

    return "\n".join(usage_lines)
def handle_local_actions(user_text: str):
    text = user_text.lower().strip()

    add_keywords = [
        "add",
        "create",
        "put",
        "save",
        "make"
    ]

    todo_keywords = [
        "todo",
        "to do",
        "task",
        "checklist"
    ]

    if any(word in text for word in add_keywords) and any(word in text for word in todo_keywords):
        task = user_text

        for phrase in [
            "add",
            "create",
            "put",
            "save",
            "make",
            "to my todo list",
            "to todo list",
            "to my to do list",
            "to do list",
            "todo list",
            "todo",
            "task",
            "checklist",
        ]:
            task = task.replace(phrase, "")
            task = task.replace(phrase.title(), "")

        task = task.strip(" .")

        if not task:
            task = user_text

        add_todo(task)

        return f"Done Monu, I added {task} to your todo list."

    if "show my todo" in text or "show todos" in text or "what are my tasks" in text or "my todo list" in text:
        todos_text = get_todos_text()
        return f"Here are your current tasks. {todos_text}"

    return None


def ask_vexa(user_text: str):
    local_reply = handle_local_actions(user_text)

    if local_reply:
        return local_reply

    today_usage = get_today_usage_text()
    todos_text = get_todos_text()

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

If the user asks about tasks or todos, answer using the todo list.

Keep replies short, natural, and spoken-friendly.
Do not say you do not have access to usage data.
""",
        input=user_text,
    )

    return response.output_text

def listen_for_wake_word():
    print("Vexa is sleeping... Say: Hey Vexa")

    while True:
        audio_file = record_audio(filename="wake_check.wav", duration=3)

        text = transcribe_audio(
            audio_file,
            prompt="The user may say: Hey Vexa, Hey Vexa, Hey Jarvis, Hey Monu.",
        ).lower()

        print("Wake heard:", text)

        if "hey vexa" in text or "hey vex" in text or "hey jarvis" in text:
            return True

        time.sleep(0.5)


def listen_for_command():
    speak("Hey Monu, I am listening.")
    print("Listening for command...")

    audio_file = record_audio(filename="command.wav", duration=8)

    command = transcribe_audio(
        audio_file,
        prompt=(
            "The user is speaking English or Hinglish to an AI productivity assistant named Vexa. "
            "Terms may include Cursor, Chrome, Terminal, productivity, todo, checklist, app usage, work time."
        ),
    )

    print("Command:", command)

    return command

def main():
    print("Vexa voice assistant started.")

    while True:
        listen_for_wake_word()

        command = listen_for_command()

        reply = ask_vexa(command)

        print("Vexa:", reply)
        speak(reply)

        while True:
            print("Waiting 10 seconds for follow-up...")
            audio_file = record_audio(filename="follow_up.wav", duration=10)

            follow_up = transcribe_audio(
                audio_file,
                prompt=(
                    "The user may continue speaking to Vexa after an answer. "
                    "If there is silence or no clear speech, return empty or unclear text."
                ),
            )

            follow_up_clean = follow_up.strip().lower()
            print("Follow-up heard:", follow_up_clean)

            # If Whisper heard nothing useful, go back to sleep
            if (
                not follow_up_clean
                or follow_up_clean in ["you", "thank you.", "thank you", ".", "bye."]
                or len(follow_up_clean) < 4
            ):
                print("No follow-up detected. Going back to sleep...")
                break

            reply = ask_vexa(follow_up)

            print("Vexa:", reply)
            speak(reply)

        print("Sleeping again... Say Hey Vexa to wake me.")