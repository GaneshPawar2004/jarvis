"""System skills: time, PC status, launching apps and websites (Windows)."""
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

import psutil

import config

# Spoken names -> what Windows can launch directly.
APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "file explorer": "explorer",
    "explorer": "explorer",
    "files": "explorer",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "terminal": "wt",
    "command prompt": "cmd",
    "cmd": "cmd",
    "powershell": "powershell",
    "paint": "mspaint",
    "task manager": "taskmgr",
    "settings": "ms-settings:",
    "spotify": "spotify:",
    "camera": "microsoft.windows.camera:",
}

START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]


def get_datetime() -> str:
    """Get the current local date, time and day of the week."""
    return config.now().strftime("%A, %d %B %Y, %I:%M %p (24-hour: %Y-%m-%d %H:%M)")


def system_status() -> dict:
    """Get the computer's current status: CPU usage, memory usage, disk usage and battery level."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    status = {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / 1e9, 1),
        "memory_total_gb": round(mem.total / 1e9, 1),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 1e9, 1),
    }
    battery = psutil.sensors_battery()
    if battery:
        status["battery_percent"] = round(battery.percent)
        status["charging"] = battery.power_plugged
    else:
        status["battery"] = "no battery detected"
    return status


def _find_start_menu_shortcut(name: str) -> Path | None:
    name = name.lower()
    for base in START_MENU_DIRS:
        if not base.exists():
            continue
        for lnk in base.rglob("*.lnk"):
            if name in lnk.stem.lower():
                return lnk
    return None


def open_application(name: str) -> str:
    """Open an application on the user's Windows computer.

    Args:
        name: The application name, e.g. "chrome", "notepad", "calculator", "vs code", "spotify".
    """
    key = name.strip().lower()
    target = APP_ALIASES.get(key, key)

    if target.endswith(":"):  # URI-launched apps (settings, spotify, camera)
        os.startfile(target)
        return f"Opened {name}."
    if shutil.which(target):
        subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=subprocess.CREATE_NO_WINDOW)
        return f"Opened {name}."
    shortcut = _find_start_menu_shortcut(key)
    if shortcut:
        os.startfile(shortcut)
        return f"Opened {shortcut.stem}."
    try:  # apps registered with Windows but not on PATH (e.g. chrome)
        os.startfile(target)
        return f"Opened {name}."
    except OSError:
        return f"Could not find an application called '{name}' on this computer."


def open_website(url: str) -> str:
    """Open a website in the user's default web browser.

    Args:
        url: The website address, e.g. "youtube.com" or "https://github.com".
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."
