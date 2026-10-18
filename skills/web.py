"""Web skills: live internet search."""
from ddgs import DDGS


def web_search(query: str) -> list[dict] | str:
    """Search the internet for current information (news, weather, facts, prices, people).

    Args:
        query: What to search for.
    """
    try:
        results = DDGS().text(query, max_results=5)
    except Exception as e:  # network errors, rate limits
        return f"Search failed: {e}"
    return [{"title": r["title"], "url": r["href"], "snippet": r["body"]} for r in results]
