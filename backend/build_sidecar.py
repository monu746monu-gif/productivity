from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
TAURI_BIN_DIR = ROOT / "src-tauri" / "binaries"
SIDE_CAR_NAME = "vexa-backend"


def target_triple() -> str:
    machine = platform.machine().lower()

    if sys.platform != "darwin":
        raise SystemExit("This build helper currently targets macOS only.")

    if machine in {"arm64", "aarch64"}:
        return "aarch64-apple-darwin"

    if machine in {"x86_64", "amd64"}:
        return "x86_64-apple-darwin"

    raise SystemExit(f"Unsupported macOS architecture: {machine}")


def build_sidecar():
    env = os.environ.copy()
    env.setdefault("PYINSTALLER_CONFIG_DIR", "/private/tmp/vexa-pyinstaller-config")
    env.setdefault("XDG_CACHE_HOME", "/private/tmp/vexa-pyinstaller-cache")

    TAURI_BIN_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        str(BACKEND_DIR / "venv" / "bin" / "pyinstaller"),
        "--onefile",
        "--name",
        SIDE_CAR_NAME,
        "--distpath",
        str(TAURI_BIN_DIR),
        "--workpath",
        str(BACKEND_DIR / "build"),
        "--specpath",
        str(BACKEND_DIR / "build"),
        str(BACKEND_DIR / "sidecar_main.py"),
    ]

    subprocess.run(command, cwd=ROOT, env=env, check=True)

    built_binary = TAURI_BIN_DIR / SIDE_CAR_NAME
    suffixed_binary = TAURI_BIN_DIR / f"{SIDE_CAR_NAME}-{target_triple()}"

    shutil.copy2(built_binary, suffixed_binary)
    os.chmod(suffixed_binary, 0o755)

    print(f"Built sidecar: {suffixed_binary}")


if __name__ == "__main__":
    build_sidecar()
