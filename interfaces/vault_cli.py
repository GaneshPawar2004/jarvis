"""Vault manager: the user adds, views and deletes their personal details directly.
Nothing typed here goes to the AI."""
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from core import vault

console = Console()


def show() -> None:
    entries = vault.load()
    if not entries:
        console.print("[dim]The vault is empty.[/]\n")
        return
    table = Table(title="Your saved details (masked)", header_style="bold cyan")
    for column in ("Key", "Field", "Category", "Value"):
        table.add_column(column)
    for key, e in sorted(entries.items(), key=lambda kv: (kv[1]["category"], kv[0])):
        value = vault.mask(e["value"]) if e["sensitive"] else e["value"]
        table.add_row(key, e["label"] + (" 🔒" if e["sensitive"] else ""), e["category"], value)
    console.print(table)
    console.print()


def _ask_value(label: str, sensitive: bool) -> str:
    return Prompt.ask(f"  {label}", password=sensitive, default="", show_default=False).strip()


def guided_setup() -> None:
    console.print("[dim]Press Enter to skip a field. ID numbers are hidden while you type.[/]")
    entries = vault.load()
    category = None
    for key, (label, cat, sensitive) in vault.TEMPLATE.items():
        if cat != category:
            category = cat
            console.print(f"\n[bold cyan]{cat}[/]")
        saved = " [dim](saved, Enter keeps it)[/]" if key in entries else ""
        value = _ask_value(label + saved, sensitive)
        if value:
            vault.set_field(key, value)
    console.print("\n[green]Saved.[/]\n")


def add_custom() -> None:
    label = Prompt.ask("  Field name (e.g. 'Employee ID', 'Blood group')").strip()
    if not label:
        return
    key = "_".join(label.lower().split())
    sensitive = Confirm.ask("  Is it sensitive (an ID or account number)?", default=False)
    value = _ask_value(label, sensitive)
    if value:
        vault.set_field(key, value, label=label, category="Custom", sensitive=sensitive)
        console.print(f"[green]Saved as '{key}'.[/]\n")


def edit_one() -> None:
    key = Prompt.ask("  Key to add or change (see the table, e.g. 'email')").strip().lower()
    if not key:
        return
    label, _, sensitive = vault.TEMPLATE.get(key, (key.replace("_", " ").capitalize(), "Custom", False))
    value = _ask_value(label, sensitive)
    if value:
        vault.set_field(key, value)
        console.print("[green]Saved.[/]\n")


def delete_one() -> None:
    key = Prompt.ask("  Key to delete").strip().lower()
    if key and Confirm.ask(f"  Delete '{key}'?", default=False):
        console.print("[green]Deleted.[/]\n" if vault.delete_field(key) else "[yellow]No such key.[/]\n")


def run() -> None:
    console.print("[bold cyan]🔒 JARVIS vault[/] — encrypted with your Windows login. "
                  "JARVIS's AI never sees these values.\n")
    actions = {"1": show, "2": guided_setup, "3": edit_one, "4": add_custom, "5": delete_one}
    while True:
        console.print("[bold]1[/] Show  [bold]2[/] Guided setup  [bold]3[/] Add/change one  "
                      "[bold]4[/] Add custom field  [bold]5[/] Delete  [bold]6[/] Exit")
        choice = Prompt.ask("Choose", choices=list(actions) + ["6"], default="1")
        if choice == "6":
            break
        actions[choice]()
