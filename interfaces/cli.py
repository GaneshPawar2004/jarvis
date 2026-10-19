"""Text chat interface in the terminal."""
from rich.console import Console
from rich.prompt import Confirm

import config
from core import confirm, history, memory
from core.remote import connect_brain

console = Console()
_status = None  # the 'Thinking…' spinner, paused while asking the user

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝"""


def show_tool(name: str, args: dict) -> None:
    detail = ", ".join(f"{k}={v!r}" for k, v in args.items())
    console.print(f"  [dim cyan]⚙ {name}({detail})[/]")


def show_memory() -> None:
    console.print("[bold cyan]Facts I remember:[/]")
    for fact in memory.all_facts() or ["(nothing yet)"]:
        console.print(f"  • {fact}")
    console.print("[bold cyan]Recent conversations:[/]")
    for when, text in history.recent_summaries(limit=10) or [("", "(none yet)")]:
        console.print(f"  • [dim]{when}[/] {text}")
    console.print()


def ask_user(question: str) -> bool:
    if _status:
        _status.stop()
    try:
        return Confirm.ask(f"[bold yellow]⚠ {question}[/]", default=False)
    finally:
        if _status:
            _status.start()


def run() -> None:
    global _status
    console.print(f"[bold cyan]{BANNER}[/]")
    console.print("[dim]Type your message. Commands: /memory (what I remember), /reset (clear chat), /exit[/]\n")
    with console.status("[cyan]Connecting to cloud JARVIS…[/]", spinner="dots"):
        brain, note = connect_brain(on_tool=show_tool)
    console.print(f"[dim]{note}[/]\n")
    confirm.set_handler(ask_user)

    while True:
        try:
            text = console.input("[bold yellow]You ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            text = "/exit"
        if not text:
            continue
        if text in ("/exit", "/quit", "exit", "quit"):
            with console.status("[cyan]Saving memories…[/]", spinner="dots"):
                brain.close()
            console.print(f"[bold cyan]JARVIS ›[/] Powering down. Goodbye, {config.USER_NAME}.")
            break
        if text == "/reset":
            with console.status("[cyan]Saving memories…[/]", spinner="dots"):
                brain.reset()
            console.print("[dim]Conversation cleared.[/]")
            continue
        if text == "/memory":
            show_memory()
            continue

        try:
            with console.status("[cyan]Thinking…[/]", spinner="dots") as _status:
                reply = brain.ask(text)
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")
            continue
        finally:
            _status = None
        console.print(f"[bold cyan]JARVIS ›[/] {reply}  [dim]({brain.active_model})[/]\n")
