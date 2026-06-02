import os


def get_openai_api_key():
    return os.getenv("OPENAI_API_KEY", "").strip()


def is_openai_api_key_managed():
    return True


def has_openai_api_key():
    return bool(get_openai_api_key().strip())
