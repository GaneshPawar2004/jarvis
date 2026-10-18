"""Reminder storage and Windows Task Scheduler helpers (kept light so notify.py starts fast)."""
import base64
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config

REMINDERS_FILE = config.DATA_DIR / "reminders.json"
TASK_FOLDER = "\\JARVIS\\"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
NOTIFY_SCRIPT = config.ROOT / "notify.py"


def load() -> list[dict]:
    try:
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save(reminders: list[dict]) -> None:
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2, ensure_ascii=False), encoding="utf-8")


def _powershell(script: str) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()  # sidesteps command-line quoting
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def task_name(reminder_id: int) -> str:
    return f"Reminder {reminder_id}"


def register(reminder_id: int, when: datetime) -> subprocess.CompletedProcess:
    return _powershell(
        f"$a = New-ScheduledTaskAction -Execute '{PYTHONW}' "
        f"-Argument '\"{NOTIFY_SCRIPT}\" {reminder_id}' -WorkingDirectory '{config.ROOT}'; "
        f"$t = New-ScheduledTaskTrigger -Once -At ([datetime]'{when:%Y-%m-%dT%H:%M:00}'); "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; "
        f"Register-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{task_name(reminder_id)}' "
        "-Action $a -Trigger $t -Settings $s -Force | Out-Null"
    )


def unregister(reminder_id: int) -> None:
    _powershell(
        f"Unregister-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{task_name(reminder_id)}' "
        "-Confirm:$false -ErrorAction SilentlyContinue"
    )
