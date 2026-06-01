PRODUCTIVE_APPS = [
    "Cursor",
    "Visual Studio Code",
    "VS Code",
    "Terminal",
    "iTerm2",
    "Figma",
    "Notion",
    "Xcode",
    "Sublime Text",
    "Postman",
]

DISTRACTING_APPS = [
    "YouTube",
    "Netflix",
    "Instagram",
    "TikTok",
    "Spotify",
    "Discord",
    "Games",
]

NEUTRAL_APPS = [
    "Google Chrome",
    "Safari",
    "Finder",
    "Preview",
    "Mail",
    "Messages",
]


def classify_app(app_name: str):
    name = app_name.lower()

    for app in PRODUCTIVE_APPS:
        if app.lower() in name:
            return "productive"

    for app in DISTRACTING_APPS:
        if app.lower() in name:
            return "distracting"

    for app in NEUTRAL_APPS:
        if app.lower() in name:
            return "neutral"

    return "neutral"