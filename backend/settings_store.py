import json
import os
from pathlib import Path


CONFIG_DIR = Path.home() / ".vexa"
CONFIG_FILE = CONFIG_DIR / "config.json"


def read_config():
    if not CONFIG_FILE.is_file():
        return {}

    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_openai_api_key():
    config = read_config()
    return config.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")


def is_openai_api_key_managed():
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def has_openai_api_key():
    return bool(get_openai_api_key().strip())


def save_openai_api_key(api_key: str):
    config = read_config()
    config["openai_api_key"] = api_key.strip()
    write_config(config)
