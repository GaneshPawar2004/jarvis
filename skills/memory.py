"""Memory skills: let the AI save and delete long-term facts about the user."""
from core import history, memory


def remember(fact: str) -> str:
    """Save an important long-term fact about the user (name, preferences, projects, people,
    routines) so it is remembered in future conversations.

    Args:
        fact: The fact to remember, written as a full sentence, e.g. "The user's birthday is 5 March."
    """
    memory.add_fact(fact)
    return "Saved to memory."


def forget(text: str) -> str:
    """Delete saved memories that contain the given text.

    Args:
        text: Words identifying the memory to delete.
    """
    removed = memory.remove_fact(text)
    return f"Removed {removed} memory item(s)."


def recall_conversations(query: str) -> list[dict] | str:
    """Search all past conversations with the user, by meaning, for things discussed before
    (e.g. "what did we decide about the website", "the book I mentioned last week").

    Args:
        query: What to look for in past conversations.
    """
    results = history.search(query)
    return results or "Nothing relevant found in past conversations."
