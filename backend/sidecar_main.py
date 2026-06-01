import threading

import uvicorn

from main import app
from tracker import start_tracker


def start_tracker_thread():
    tracker_thread = threading.Thread(target=start_tracker, daemon=True)
    tracker_thread.start()
    return tracker_thread


def main():
    start_tracker_thread()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
