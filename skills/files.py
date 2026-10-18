"""File skills: find files in the user's folders and open them."""
import os
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
SEARCH_ROOTS = [HOME / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")]
SEARCH_ROOTS += [p for p in HOME.glob("OneDrive*") if p.is_dir()]
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "AppData", "$RECYCLE.BIN"}
BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr", ".com", ".reg", ".jar"}
MAX_RESULTS = 15
TIME_LIMIT = 8.0


def find_files(name: str, extension: str = "") -> list[dict] | str:
    """Search the user's Desktop, Documents, Downloads, Pictures, Music, Videos and OneDrive
    folders for files whose name contains the given text. Newest files come first.

    Args:
        name: Part of the file name to look for (not case-sensitive), e.g. "resume" or "invoice".
        extension: Optional file type filter, e.g. "pdf", "docx", "jpg". Leave empty for any type.
    """
    needle = name.lower().strip()
    ext = "." + extension.lower().lstrip(".") if extension else ""
    deadline = time.monotonic() + TIME_LIMIT
    found: dict[Path, float] = {}

    for root in SEARCH_ROOTS:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                lower = f.lower()
                if needle in lower and (not ext or lower.endswith(ext)):
                    path = Path(folder) / f
                    try:
                        found[path] = path.stat().st_mtime
                    except OSError:
                        pass
            if time.monotonic() > deadline:
                break

    if not found:
        return f"No files matching '{name}' found."
    newest = sorted(found.items(), key=lambda item: item[1], reverse=True)[:MAX_RESULTS]
    return [
        {"path": str(p), "modified": datetime.fromtimestamp(m).strftime("%d %b %Y %H:%M")}
        for p, m in newest
    ]


def open_file(path: str) -> str:
    """Open a file or folder with its default app (documents, images, videos, folders).
    Programs and scripts are not allowed; use open_application for apps.

    Args:
        path: Full path to the file or folder, usually taken from find_files results.
    """
    target = Path(path).expanduser()
    if not target.exists():
        return f"'{path}' does not exist."
    if target.suffix.lower() in BLOCKED_EXTENSIONS:
        return f"For safety I won't run program or script files ({target.suffix})."
    os.startfile(target)
    return f"Opened {target.name}."
