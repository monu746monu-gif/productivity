import json
from openai import OpenAI


def detect_intent(client: OpenAI, user_text: str):
    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="""
You are an intent detection system for a voice-first AI productivity assistant called Vexa.

Convert the user's message into JSON only.

Possible intents:

1. add_todo
Use when user wants to add/create/save a task.

2. delete_todo
Use when user wants to remove/delete/take out/clear a task.

3. complete_todo
Use when user says a task is done, finished, completed, or should be marked complete.

4. show_todos
Use when user asks what tasks/todos/checklist items they have.

5. ask_usage
Use when user asks about app usage, productivity time, Cursor time, Chrome time, work time, focus time, or how much time they spent.

6. daily_report
Use when user asks for daily report, productivity summary, how was my day, or what should I improve.

7. save_idea
Use when user wants to remember, save, note, store, or capture an idea.

8. show_ideas
Use when user asks what ideas they saved, show my ideas, read my ideas, or recall my ideas.

9. add_reminder
Use when user asks to remind them about something, schedule a reminder, meeting, call, or event.

10. show_reminders
Use when user asks what reminders, calls, meetings, or scheduled reminders they have.

11. general_chat
Use for anything else.

Return JSON in this exact format:
{
  "intent": "add_todo | delete_todo | complete_todo | show_todos | ask_usage | daily_report | save_idea | show_ideas | add_reminder | show_reminders | general_chat",
  "task": "task name if relevant, otherwise empty string",
  "app_name": "app name if relevant, otherwise empty string",
  "idea": "idea content if relevant, otherwise empty string",
  "reminder_title": "reminder title if relevant, otherwise empty string",
  "reminder_time": "reminder time in natural language if relevant, otherwise empty string"
}

Rules:
- Return only valid JSON.
- No markdown.
- No explanation.
- If user says "I finished X", intent is complete_todo and task is X.
- If user says "remove X from my list", intent is delete_todo and task is X.
- If user says "add X to my todo", intent is add_todo and task is X.
- If user says "what are my tasks", intent is show_todos.
- If user asks "how much time did I spend on Cursor", intent is ask_usage and app_name is Cursor.
- If user says "remember this idea X", intent is save_idea and idea is X.
- If user says "save this idea X", intent is save_idea and idea is X.
- If user says "what ideas did I save", intent is show_ideas.
- If user says "remind me about meeting at 8 AM", intent is add_reminder, reminder_title is meeting, reminder_time is 8 AM.
- If user says "remind me to call Rahul at 7 PM", intent is add_reminder, reminder_title is call Rahul, reminder_time is 7 PM.
- If user says "show my reminders", intent is show_reminders.
""",
        input=user_text,
    )

    raw = response.output_text.strip()

    try:
        data = json.loads(raw)

        return {
            "intent": data.get("intent", "general_chat"),
            "task": data.get("task", ""),
            "app_name": data.get("app_name", ""),
            "idea": data.get("idea", ""),
            "reminder_title": data.get("reminder_title", ""),
            "reminder_time": data.get("reminder_time", ""),
        }

    except json.JSONDecodeError:
        return {
            "intent": "general_chat",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }