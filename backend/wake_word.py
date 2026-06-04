import os
import subprocess
import time
import sqlite3
from datetime import datetime
from storage import get_db_path
from todos import add_todo, get_todos_text
from ideas import save_idea, get_ideas_text
from intent import (
    TIME_PATTERN,
    detect_intent,
    has_idea_language,
    has_reminder_language,
    has_todo_language,
    strip_command_words,
)
from reminders import add_reminder, get_reminders_text, parse_reminder_time
from dotenv import load_dotenv
from openai import OpenAI

from recorder import record_audio

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

pending_action = {
    "type": "",
    "title": "",
}


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
    conn = sqlite3.connect(get_db_path(), timeout=1)
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


def save_reminder_from_parts(title: str, reminder_time: str):
    remind_at = parse_reminder_time(reminder_time)

    if not remind_at:
        return None

    add_reminder(title, remind_at.isoformat())
    spoken_time = remind_at.strftime("%I:%M %p").lstrip("0")
    return f"Okay Misu, I will remind you about {title} at {spoken_time}."


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

    intent_data = detect_intent(client, user_text)
    intent = intent_data.get("intent", "general_chat")

    if intent == "add_todo":
        if not has_todo_language(user_text.lower()):
            if has_reminder_language(user_text.lower()):
                intent = "add_reminder"
            elif has_idea_language(user_text.lower()):
                intent = "save_idea"
                intent_data["idea"] = intent_data.get("idea") or intent_data.get("task") or user_text
            else:
                return "Should I save that as an idea or add it as a todo, Misu?"

    if intent == "add_todo":
        task = intent_data.get("task", "").strip()

        if not task:
            return "What task should I add, Misu?"

        add_todo(task)
        return f"Done Misu, I added {task} to your todo list."

    if intent == "show_todos":
        todos_text = get_todos_text()
        return f"Here are your current tasks. {todos_text}"

    if intent == "save_idea":
        idea = intent_data.get("idea", "").strip()

        if not idea:
            return "What idea should I save, Misu?"

        save_idea(idea)
        return f"Got it, Misu. I saved that idea: {idea}"

    if intent == "show_ideas":
        ideas_text = get_ideas_text()
        return f"Here are your saved ideas. {ideas_text}"

    if intent == "add_reminder":
        reminder_title = intent_data.get("reminder_title", "").strip()
        reminder_time = intent_data.get("reminder_time", "").strip()

        if not reminder_title:
            pending_action["type"] = "add_reminder"
            pending_action["title"] = ""
            return "What should I remind you about, Misu?"

        if not reminder_time:
            pending_action["type"] = "add_reminder"
            pending_action["title"] = reminder_title
            return f"When should I remind you about {reminder_title}?"

        reply = save_reminder_from_parts(reminder_title, reminder_time)

        if not reply:
            return f"I heard the reminder, but not the time. When should I remind you about {reminder_title}?"

        return reply

    if intent == "show_reminders":
        reminders_text = get_reminders_text()
        return f"Here are your upcoming reminders. {reminders_text}"

    return None


def ask_vexa(user_text: str):
    local_reply = handle_local_actions(user_text)

    if local_reply:
        return local_reply

    today_usage = get_today_usage_text()
    todos_text = get_todos_text()
    ideas_text = get_ideas_text()
    reminders_text = get_reminders_text()

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions=f"""
You are Vexa, a friendly voice-first AI productivity companion.
The user's name is Misu.

Today's app usage data:
{today_usage}

Current todo list:
{todos_text}

Saved ideas:
{ideas_text}

Upcoming reminders:
{reminders_text}

If the user asks about Cursor, Chrome, Terminal, productivity time, work time, focus time, or app usage,
answer directly using today's data.

If the user asks about tasks or todos, answer using the todo list.
If the user asks about saved ideas, answer using saved ideas.
If the user asks about reminders, calls, meetings, or scheduled things, answer using upcoming reminders.

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
            prompt="The user may say: Hey Vexa, Hey Vexa, Hey Jarvis, Hey Misu.",
        ).lower()

        print("Wake heard:", text)

        if "hey vexa" in text or "hey vex" in text or "hey jarvis" in text:
            return True

        time.sleep(0.5)


def listen_for_command():
    speak("Hey Misu, what's going on?")
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
