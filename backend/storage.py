from pathlib import Path


APP_DATA_DIR = Path.home() / ".vexa"
DB_PATH = APP_DATA_DIR / "vexa.db"


def ensure_app_data_dir():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_db_path():
    ensure_app_data_dir()
    return DB_PATH
