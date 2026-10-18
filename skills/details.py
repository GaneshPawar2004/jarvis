"""Vault skills: let the AI see WHICH personal details are saved (never the values)."""
from core import vault


def vault_list_fields() -> list[dict] | str:
    """List the user's saved personal details by key and label (name, email, address,
    education, work, ID numbers...). Values are hidden; fill them with phone_fill_field."""
    entries = vault.load()
    if not entries:
        return "The vault is empty. The user can add details with option 5 in jarvis.bat."
    return [
        {"key": key, "label": e["label"], "category": e["category"], "sensitive": e["sensitive"]}
        for key, e in entries.items()
    ]


def vault_save_field(key: str, value: str, label: str = "") -> str:
    """Save a non-sensitive detail the user told you in chat (e.g. a new email or city) into
    the vault for future forms. ID numbers must be added by the user in the vault manager.

    Args:
        key: Short snake_case key, e.g. "email", "city", "employee_id".
        value: The value the user gave.
        label: Human-readable name, e.g. "Work email". Optional for standard keys.
    """
    if vault.TEMPLATE.get(key, ("", "", False))[2]:
        return "ID numbers must be added by the user in the vault manager (option 5 in jarvis.bat), not via chat."
    vault.set_field(key.strip().lower(), value, label)
    return f"Saved {label or key} to the vault."
