import json
import re
from openai import OpenAI


TIME_PATTERN = re.compile(
    r"\b(?:at\s+)?\d{1,2}(?:(?::|\s)\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\b",
    re.I,
)

TODO_WORDS = ["todo", "to do", "task", "checklist", "action item"]
TODO_ADD_WORDS = ["add", "create", "put", "make"]
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
IDEA_DISCUSSION_PHRASES = [
    "discuss this idea with you",
    "discuss this idea",
    "discuss the idea with you",
    "discuss the idea",
    "discuss an idea with you",
    "discuss an idea",
    "discuss idea with you",
    "discuss idea",
    "talk about this idea",
    "talk about the idea",
    "talk about an idea",
    "talk through this idea",
    "talk through the idea",
    "talk through an idea",
    "brainstorm this idea with you",
    "brainstorm the idea with you",
    "brainstorm an idea with you",
    "brainstorm with you",
    "i want to discuss this idea with you",
    "i want to discuss the idea with you",
    "i want to discuss an idea with you",
    "i want to discuss idea with you",
    "let's discuss this idea",
    "lets discuss this idea",
    "let's discuss the idea",
    "lets discuss the idea",
]
USAGE_QUESTION_PHRASES = [
    "how productive was i today",
    "how productive have i been today",
    "how much did i work today",
    "how much focus time did i have",
    "how much productive time",
    "how much time did i spend",
    "how did i spend my day",
    "how have i spent my day",
    "what did i do today",
    "where did my time go",
]
DAILY_REPORT_PHRASES = [
    "how was my day",
    "give me my daily report",
    "daily report",
    "summarize my day",
    "summary of my day",
    "what should i improve",
    "give me a productivity summary",
    "productivity summary",
]
PENDING_TODO_PHRASES = [
    "what is pending",
    "what's pending",
    "show pending tasks",
    "show pending todos",
    "pending tasks",
    "pending todos",
    "what do i still have to do",
]
DONE_TODO_PHRASES = [
    "what is done",
    "what's done",
    "show completed tasks",
    "show completed todos",
    "completed tasks",
    "completed todos",
    "finished tasks",
    "done tasks",
]


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


def has_idea_discussion_language(text: str):
    return any(phrase in text for phrase in IDEA_DISCUSSION_PHRASES)


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


def extract_todo_from_patterns(user_text: str):
    patterns = [
        r"\b(?:add|create|put|save|make)\s+(.+?)\s+(?:to|on|into)\s+(?:my\s+)?(?:todo|to do|task list|list)\b",
        r"\b(?:add|create|put|save|make)\s+(.+?)\s+as\s+(?:a\s+)?(?:todo|task|action item)\b",
        r"\b(?:i need to|i have to|i should|i must)\s+(.+)",
        r"\b(?:my task is to|one task is to)\s+(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_text, flags=re.I)

        if match:
            task = match.group(1).strip(" .,:;-")

            if task:
                return task

    return ""


def extract_todo_completion_text(user_text: str):
    patterns = [
        r"\b(?:i finished|i completed|i did|i am done with|i'm done with)\s+(.+)",
        r"\b(?:mark|set)\s+(.+?)\s+as\s+(?:done|completed|finished)\b",
        r"\b(.+?)\s+(?:is|was)\s+(?:done|completed|finished)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_text, flags=re.I)

        if match:
            task = match.group(1).strip(" .,:;-")

            if task:
                return task

    return ""


def extract_todo_delete_text(user_text: str):
    patterns = [
        r"\b(?:remove|delete|clear|take off|take out)\s+(.+?)\s+(?:from\s+)?(?:my\s+)?(?:todo|to do|task list|list)\b",
        r"\b(?:remove|delete|clear|take off|take out)\s+(.+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, user_text, flags=re.I)

        if match:
            task = match.group(1).strip(" .,:;-")

            if task:
                normalized_task = task.lower()

                if normalized_task in {
                    "my",
                    "all",
                    "everything",
                    "all tasks",
                    "all task",
                    "all the tasks",
                    "all the task",
                    "the tasks",
                    "the task",
                    "entire list",
                    "whole list",
                    "my list",
                    "todo list",
                    "to do list",
                }:
                    return "__all__"

                return task

    return ""


def clean_reminder_title(user_text: str):
    title = TIME_PATTERN.sub(" ", user_text)
    title = strip_command_words(
        title,
        [
            "remember",
            "remember this",
            "remind",
            "remind me",
            "set reminder",
            "create reminder",
            "save reminder",
            "i want you to",
            "i want to",
            "i need to",
            "please",
            "that",
            "this",
            "about",
            "for",
            "at",
            "on",
            "to",
        ],
    )
    title = re.sub(r"^(?:check upon|check on|check|look at|review)\s+", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" .,:;-")
    return title


def detect_rule_based_intent(user_text: str):
    text = user_text.lower().strip()
    time_match = TIME_PATTERN.search(user_text)

    if any(phrase in text for phrase in DAILY_REPORT_PHRASES):
        return {
            "intent": "daily_report",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(phrase in text for phrase in USAGE_QUESTION_PHRASES):
        return {
            "intent": "ask_usage",
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

    if any(phrase in text for phrase in PENDING_TODO_PHRASES):
        return {
            "intent": "show_todos",
            "task": "__pending__",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(phrase in text for phrase in DONE_TODO_PHRASES):
        return {
            "intent": "show_todos",
            "task": "__done__",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if has_idea_discussion_language(text):
        return {
            "intent": "general_chat",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if any(
        phrase in text
        for phrase in [
            "show my todo",
            "show todos",
            "what are my tasks",
            "what are my todos",
            "what tasks",
            "what is on my list",
            "what's on my list",
            "read my todo",
            "read my tasks",
        ]
    ):
        return {
            "intent": "show_todos",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    completed_task = extract_todo_completion_text(user_text)

    if completed_task:
        return {
            "intent": "complete_todo",
            "task": completed_task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    deleted_task = extract_todo_delete_text(user_text)

    if deleted_task:
        return {
            "intent": "delete_todo",
            "task": deleted_task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    natural_task = extract_todo_from_patterns(user_text)

    if natural_task and time_match and has_reminder_language(text):
        reminder_title = clean_reminder_title(natural_task) or natural_task
        return {
            "intent": "add_reminder",
            "task": "",
            "app_name": "",
            "idea": "",
            "reminder_title": reminder_title,
            "reminder_time": time_match.group(0),
        }

    if natural_task and not has_idea_language(text):
        return {
            "intent": "add_todo",
            "task": natural_task,
            "app_name": "",
            "idea": "",
            "reminder_title": "",
            "reminder_time": "",
        }

    if has_reminder_language(text):
        reminder_time = time_match.group(0) if time_match else ""
        title = clean_reminder_title(user_text)

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

    if (
        (has_idea_language(text) or any(phrase in text for phrase in idea_phrases))
        and not has_idea_discussion_language(text)
    ):
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
- If user says "what is pending" or "show pending tasks", intent is show_todos and task is __pending__.
- If user says "what is done" or "show completed tasks", intent is show_todos and task is __done__.
- If user asks "how much time did I spend on Cursor", intent is ask_usage and app_name is Cursor.
- If user asks "how productive was I today" or "how did I spend my day", intent is ask_usage.
- If user asks "how was my day" or "give me my daily report", intent is daily_report.
- If user says "I have to X" or "I need to X", intent is add_todo and task is X.
- If user says "I finished X" or "X is done", intent is complete_todo and task is X.
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
