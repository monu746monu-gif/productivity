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

6. general_chat
Use for anything else.

daily_report
Use when user asks for daily report, summary of the day, productivity summary, how was my day, or what should I improve.

Return JSON in this exact format:
{
  "intent": "add_todo | delete_todo | complete_todo | show_todos | ask_usage | general_chat",
  "task": "task name if relevant, otherwise empty string",
  "app_name": "app name if relevant, otherwise empty string"
}

Rules:
- Return only valid JSON.
- No markdown.
- No explanation.
- If the user says "I finished X", intent is complete_todo and task is X.
- If the user says "remove X from my list", intent is delete_todo and task is X.
- If the user says "add X to my todo", intent is add_todo and task is X.
- If user asks "what are my tasks", intent is show_todos.
- If user asks "how much time did I spend on Cursor", intent is ask_usage and app_name is Cursor.
""",
        input=user_text,
    )

    raw = response.output_text.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "intent": "general_chat",
            "task": "",
            "app_name": "",
        }