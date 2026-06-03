import json
import re
from openai import OpenAI


TIME_PATTERN = re.compile(
    r"\b(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\b",
    re.I,
)

TODO_WORDS = ["todo", "to do", "task", "checklist", "action item"]
TODO_ADD_WORDS = ["add", "create", "put", "make"]
TODO_DELETE_WORDS = ["delete", "remove", "clear", "take out"]
IDEA_WORDS = [
    "idea",
    "thought",
    "brainstorm",
    "concept",
    "plan",
    "note",
]
IDEA_SAVE_WORDS = ["save", "remember", "note", "store", "capture"]
REMINDER_WORDS = ["remind", "reminder", "meeting", "call", "appointment", "event"]


def has_any(text: str, words):
    return any(word in text for word in words)


def has_todo_language(text: str):
    return has_any(text, TODO_WORDS)


def has_idea_language(text: str):
    return has_any(text, IDEA_WORDS) or (
        has_any(text, IDEA_SAVE_WORDS) and not has_todo_language(text)
    )


def has_reminder_language(text: str):
    return "remind me" in text or has_any(text, REMINDER_WORDS)


def strip_command_words(text: str, phrases):
    cleaned = text.strip()

    for phrase in sorted(phrases, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned, flags=re.I)

    words = re.sub(r"\s+", " ", cleaned).strip(" .,:;-").split()
    deduped_words = []

    for word in words:
        if deduped_words and deduped_words[-1].lower() == word.lower():
            continue

        deduped_words.append(word)

    return " ".join(deduped_words)


def extract_after_keyword(user_text: str, keywords):
    for keyword in keywords:
        match = re.search(rf"\b{re.escape(keyword)}\b", user_text, flags=re.I)

        if match:
            content = user_text[match.end():]
            content = strip_command_words(
                content,
                [
                    "is",
                    "that",
                    "this",
                    "about",
                    "for",
                    "to",
                    "please",
                ],
            )

            if content:
                return content

    return ""


def detect_rule_based_intent(user_text: str):
    text = user_text.lower().strip()
    time_match = TIME_PATTERN.search(user_text)

    if any(phrase in text for phrase in ["make a todo list", "make a to do list", "create a todo list", "schedule my day"]):
        task = strip_command_words(
            user_text,
            [
                "make a todo list",
                "make a to do list",
                "create a todo list",
                "schedule my day",
                "schedule",
                "my day",
                "todo list",
                "to do list",
                "please",
            ],
        )

        return {
            "intent": "add_todo",
            "task": task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(
        phrase in text
        for phrase in [
            "talk to you",
            "talk with you",
            "chat with you",
            "talk for some time",
            "talk for a while",
            "normal conversation",
            "just want to talk",
            "my day",
            "about my day",
            "how was my day",
            "i am feeling",
            "i feel",
            "i'm feeling",
            "i had a",
        ]
    ):
        return {
            "intent": "general_chat",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(phrase in text for phrase in ["show my reminders", "show reminders", "what reminders", "upcoming reminders"]):
        return {
            "intent": "show_reminders",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(phrase in text for phrase in ["show my ideas", "show ideas", "what ideas", "read my ideas"]):
        return {
            "intent": "show_ideas",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(
        phrase in text
        for phrase in [
            "what is pending",
            "what are pending",
            "what tasks are pending",
            "pending tasks",
            "show pending",
            "what is left",
            "what tasks are left",
            "what is done",
            "what are done",
            "completed tasks",
            "done tasks",
            "show my todo",
            "show todos",
            "what are my tasks",
            "what tasks",
            "read my todo",
            "read my tasks",
        ]
    ):
        return {
            "intent": "show_todos",
            "task": "__pending__" if any(phrase in text for phrase in ["pending", "left"]) else "__done__" if any(phrase in text for phrase in ["done", "completed"]) else "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(
        phrase in text
        for phrase in [
            "i am done with",
            "i'm done with",
            "i finished",
            "i completed",
            "mark done",
            "mark as done",
        ]
    ):
        task = strip_command_words(
            user_text,
            [
                "i am done with",
                "i'm done with",
                "i finished",
                "i completed",
                "mark",
                "mark as",
                "done",
                "complete",
                "completed",
                "this task",
                "this",
                "task",
                "please",
            ],
        )

        if not task and any(phrase in text for phrase in ["this task", "this"]):
            task = "__current__"

        return {
            "intent": "complete_todo",
            "task": task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if has_any(text, TODO_DELETE_WORDS) and (
        has_todo_language(text)
        or any(phrase in text for phrase in ["both", "all", "everything", "entire list", "my list"])
    ):
        task = strip_command_words(
            user_text,
            [
                "delete",
                "remove",
                "clear",
                "take out",
                "from my todo list",
                "from todo list",
                "from my to do list",
                "from my list",
                "my todo list",
                "todo list",
                "to do list",
                "todos",
                "todo",
                "tasks",
                "task",
                "both of them",
                "all of them",
                "please",
            ],
        )

        if not task and any(phrase in text for phrase in ["both", "all", "everything", "entire list", "clear"]):
            task = "__all__"

        if task.lower() in {"both", "all", "everything", "entire list", "my list"}:
            task = "__all__"

        return {
            "intent": "delete_todo",
            "task": task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if has_reminder_language(text):
        reminder_time = time_match.group(0) if time_match else ""
        title = TIME_PATTERN.sub(" ", user_text)
        title = strip_command_words(
            title,
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

        if not title:
            title = "reminder"

        return {
            "intent": "add_reminder",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": title,
            "reminder_time": reminder_time,
        }

    idea_phrases = ["save this", "remember this", "note this", "write this down", "store this"]

    if has_idea_language(text) or any(phrase in text for phrase in idea_phrases):
        idea = extract_after_keyword(user_text, IDEA_WORDS)

        if not idea:
            idea = strip_command_words(
                user_text,
                [
                    "save",
                    "remember",
                    "note",
                    "store",
                    "capture",
                    "this",
                    "my",
                    "idea",
                    "thought",
                    "brainstorm",
                    "concept",
                    "please",
                ],
            )

        return {
            "intent": "save_idea",
            "task": "",
            "app_name": "",
            "idea": idea,
            "reminder_title": "",
            "reminder_time": "",
        }

    if has_todo_language(text) and has_any(text, TODO_ADD_WORDS + ["save"]):
        task = strip_command_words(
            user_text,
            [
                "add",
                "create",
                "put",
                "save",
                "make",
                "to my todo list",
                "to todo list",
                "to my to do list",
                "as an action item",
                "as a checklist",
                "as a task",
                "to do list",
                "todo list",
                "todo",
                "task",
                "checklist",
                "action item",
                "please",
            ],
        )

        return {
            "intent": "add_todo",
            "task": task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    return None


def detect_intent(client: OpenAI, user_text: str):
    rule_based_intent = detect_rule_based_intent(user_text)

    if rule_based_intent:
        return rule_based_intent

    if client is None:
        return {
            "intent": "general_chat",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    response = client.responses.create(
        model="gpt-4.1-mini",
        instructions="""
You are an intent detection system for a voice-first AI productivity assistant called Vexa.

Convert the user's message into JSON only.

Possible intents:

1. add_todo
Use only when user wants to add/create/save a task, todo, checklist item, or action item.
Do not use for ideas, notes, memories, meetings, calls, events, or reminders.

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
Use when user wants to remember, save, note, store, or capture an idea, thought, concept, plan, or brainstorm.

8. show_ideas
Use when user asks what ideas they saved, show my ideas, read my ideas, or recall my ideas.

9. add_reminder
Use when user asks to remind them about something at a time, or mentions a meeting, call, or event with a time.

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
- If user says "save X" but X is an idea/thought/concept, intent is save_idea, not add_todo.
- If user says "remember X" and X includes a time, meeting, call, event, or "remind me", intent is add_reminder, not save_idea or add_todo.
- If user says "I have an idea X", "my idea is X", or "save my idea X", intent is save_idea and idea is X.
- If user says "what are my tasks", intent is show_todos.
- If user asks "how much time did I spend on Cursor", intent is ask_usage and app_name is Cursor.
- If user says "remember this idea X", intent is save_idea and idea is X.
- If user says "save this idea X", intent is save_idea and idea is X.
- If user says "what ideas did I save", intent is show_ideas.
- If user says "remind me about meeting at 8 AM", intent is add_reminder, reminder_title is meeting, reminder_time is 8 AM.
- If user says "remind me to call Rahul at 7 PM", intent is add_reminder, reminder_title is call Rahul, reminder_time is 7 PM.
- If user says "remember this meeting I have a meeting at 8 AM", intent is add_reminder, reminder_title is meeting, reminder_time is 8 AM.
- If user says "show my reminders", intent is show_reminders.
""",
        input=user_text,
    )

    raw = response.output_text.strip()

    try:
        data = json.loads(raw)
        intent = data.get("intent", "general_chat")
        text = user_text.lower().strip()

        if intent == "add_todo" and not has_todo_language(text):
            if has_reminder_language(text):
                reminder_data = detect_rule_based_intent(user_text)

                if reminder_data:
                    return reminder_data

            if has_idea_language(text) or has_any(text, IDEA_SAVE_WORDS):
                idea = extract_after_keyword(user_text, IDEA_WORDS)

                if not idea:
                    idea = strip_command_words(
                        user_text,
                        IDEA_SAVE_WORDS
                        + [
                            "this",
                            "my",
                            "idea",
                            "thought",
                            "brainstorm",
                            "concept",
                            "plan",
                            "note",
                            "please",
                        ],
                    )

                return {
                    "intent": "save_idea",
                    "task": "",
                    "app_name": "",
                    "idea": idea,
                    "reminder_title": "",
                    "reminder_time": "",
                }

        return {
            "intent": intent,
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
