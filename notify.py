"""Shows a reminder notification. Run by Windows Task Scheduler: pythonw notify.py <id>."""
import sys

from winotify import Notification, audio

from core import reminders


def main(reminder_id: int) -> None:
    items = reminders.load()
    reminder = next((r for r in items if r["id"] == reminder_id), None)
    if reminder and not reminder["done"]:
        toast = Notification(app_id="J.A.R.V.I.S.", title="Reminder, sir", msg=reminder["message"], duration="long")
        toast.set_audio(audio.Reminder, loop=False)
        toast.show()
        reminder["done"] = True
        reminders.save(items)
    reminders.unregister(reminder_id)


if __name__ == "__main__":
    main(int(sys.argv[1]))
