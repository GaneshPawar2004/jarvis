"""Reminder skills. Each reminder is a Windows scheduled task, so it pops up on time
even when JARVIS isn't running."""
from datetime import datetime

from core import reminders as store


def set_reminder(message: str, due: str) -> str:
    """Set a reminder that pops up as a Windows notification at a specific time, even if
    JARVIS is closed. Work out the exact date and time from the current time yourself.

    Args:
        message: What to remind the user about, e.g. "Call mom".
        due: Local date and time in the format "YYYY-MM-DD HH:MM", e.g. "2026-10-17 09:30".
    """
    try:
        when = datetime.strptime(due.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return "The time must be in the format YYYY-MM-DD HH:MM."
    if when <= datetime.now():
        return f"{when:%d %b %Y %H:%M} is in the past."

    reminders = store.load()
    reminder_id = max((r["id"] for r in reminders), default=0) + 1
    result = store.register(reminder_id, when)
    if result.returncode != 0:
        return f"Windows refused to schedule the reminder: {result.stderr.strip()[:300]}"

    reminders.append({"id": reminder_id, "message": message, "due": f"{when:%Y-%m-%d %H:%M}", "done": False})
    store.save(reminders)
    return f"Reminder {reminder_id} set for {when:%A %d %b at %I:%M %p}: {message}"


def list_reminders() -> list[dict] | str:
    """List the user's upcoming reminders."""
    upcoming = [r for r in store.load() if not r["done"]]
    return upcoming or "No upcoming reminders."


def cancel_reminder(reminder_id: int) -> str:
    """Cancel an upcoming reminder.

    Args:
        reminder_id: The reminder's id number, from list_reminders.
    """
    reminders = store.load()
    remaining = [r for r in reminders if r["id"] != reminder_id]
    if len(remaining) == len(reminders):
        return f"No reminder with id {reminder_id}."
    store.unregister(reminder_id)
    store.save(remaining)
    return f"Reminder {reminder_id} cancelled."
