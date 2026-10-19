"""Memory skills: let the AI save and delete long-term memories about the user."""
from core import history, memory


def remember(fact: str, kind: str = "fact", importance: int = 3) -> str:
    """Save something the user explicitly asked you to remember. (Other lasting details
    are saved automatically after the conversation.)

    Args:
        fact: One short sentence about the user, e.g. "The user's birthday is 5 March."
        kind: One of "person", "project", "preference", "place", "goal", "routine", "fact".
        importance: 1 to 5; 5 = core identity (name, home city, job, family).
    """
    return memory.add(fact, kind, importance=importance, source="asked")


def forget(text: str) -> str:
    """Delete memories the user wants forgotten or says are wrong.

    Args:
        text: Words describing the memory to delete.
    """
    removed = memory.forget(text)
    return f"Removed {removed} memory item(s)."


def recall_conversations(query: str) -> list[dict] | str:
    """Search all past conversations with the user, by meaning, for things discussed before
    (e.g. "what did we decide about the website", "the book I mentioned last week").

    Args:
        query: What to look for in past conversations.
    """
    results = history.search(query)
    return results or "Nothing relevant found in past conversations."
