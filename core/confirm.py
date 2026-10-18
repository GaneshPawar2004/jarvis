"""Human confirmation gate. Risky tools call ask(); each interface installs a handler that
puts the question to the user directly (not via the AI), so the model can't approve itself."""
from typing import Callable

_handler: Callable[[str], bool] | None = None


def set_handler(handler: Callable[[str], bool] | None) -> None:
    global _handler
    _handler = handler


def ask(question: str) -> bool:
    """True only if the user explicitly approved. Denies when no interface can ask."""
    if _handler is None:
        return False
    try:
        return bool(_handler(question))
    except Exception:
        return False
