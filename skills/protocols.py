"""Protocols: the user's own named routines, Tony-style ("Focus protocol", "Night protocol").
JARVIS saves the steps once; saying the name later runs them with its normal tools."""
import config
from core import db


def _key(name: str) -> str:
    return " ".join(name.lower().replace("protocol", "").split())


def save_protocol(name: str, steps: str) -> str:
    """Save (or replace) a named routine the user can run later by saying its name, e.g.
    "Focus protocol: open VS Code on my laptop, play music, remind me in 50 minutes".

    Args:
        name: The protocol's name, e.g. "Focus".
        steps: The steps in plain words, in order, one per line or separated by commas.
    """
    key = _key(name)
    if not key:
        return "Give the protocol a name."
    db.execute("DELETE FROM protocols WHERE name = ?", (key,))
    db.execute("INSERT INTO protocols (name, steps, updated) VALUES (?, ?, ?)",
               (key, steps.strip(), config.now().isoformat(timespec="seconds")))
    return f"Saved the {key} protocol."


def get_protocol(name: str) -> str:
    """Get a saved protocol's steps so you can carry them out now, in order, with your tools.

    Args:
        name: The protocol's name, e.g. "Focus".
    """
    found = db.rows("SELECT steps FROM protocols WHERE name = ?", (_key(name),))
    if not found:
        names = [r[0] for r in db.rows("SELECT name FROM protocols ORDER BY name")]
        return f"No protocol called '{name}'. Saved protocols: {', '.join(names) or 'none yet'}."
    return f"Steps of the {_key(name)} protocol (do them now, in order): {found[0][0]}"


def list_protocols() -> list[dict] | str:
    """List the user's saved protocols and their steps."""
    rows = db.rows("SELECT name, steps FROM protocols ORDER BY name")
    return [{"name": n, "steps": s} for n, s in rows] or "No protocols saved yet."


def delete_protocol(name: str) -> str:
    """Delete a saved protocol.

    Args:
        name: The protocol's name.
    """
    if not db.rows("SELECT name FROM protocols WHERE name = ?", (_key(name),)):
        return f"No protocol called '{name}'."
    db.execute("DELETE FROM protocols WHERE name = ?", (_key(name),))
    return f"Deleted the {_key(name)} protocol."
