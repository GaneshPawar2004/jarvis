"""Connection to the user's Android phone over ADB (Wi-Fi debugging), with auto-reconnect."""
import os
import re
import shutil
import subprocess
from pathlib import Path

ADB = (
    os.getenv("JARVIS_ADB")
    or shutil.which("adb")
    or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe")
)

_serial: str | None = None


class PhoneError(RuntimeError):
    pass


def _adb(*args: str, timeout: float = 20, serial: str | None = None) -> subprocess.CompletedProcess:
    cmd = [ADB, *(["-s", serial] if serial else []), *args]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    except FileNotFoundError:
        raise PhoneError("ADB is not installed (Android platform-tools).")
    except subprocess.TimeoutExpired:
        raise PhoneError("The phone took too long to respond.")


def _connected() -> list[str]:
    out = _adb("devices").stdout.decode(errors="replace")
    return [line.split()[0] for line in out.splitlines()[1:] if line.strip().endswith("device")]


def device() -> str:
    """Serial of the connected phone, reconnecting over Wi-Fi if needed."""
    global _serial
    connected = _connected()
    if _serial in connected:
        return _serial
    if not connected:  # Wi-Fi debugging port changes after a restart; rediscover it
        services = _adb("mdns", "services").stdout.decode(errors="replace")
        for address in re.findall(r"_adb-tls-connect\._tcp\s+([\d.]+:\d+)", services):
            _adb("connect", address)
        connected = _connected()
    if not connected:
        raise PhoneError(
            "I can't reach the phone. Make sure it's unlocked, on the same Wi-Fi, "
            "and Wireless debugging is on."
        )
    # The same phone can appear twice (ip:port and mDNS name); prefer the ip:port entry.
    _serial = next((s for s in connected if re.match(r"[\d.]+:\d+$", s)), connected[0])
    return _serial


def run(*args: str, timeout: float = 20) -> bytes:
    """Run an adb command against the phone and return stdout (raises on failure)."""
    result = _adb(*args, timeout=timeout, serial=device())
    output = result.stdout + result.stderr
    if b"INJECT_EVENTS" in output:
        raise PhoneError(
            "The phone is blocking taps and typing. On the phone, turn on Developer options → "
            "'USB debugging (Security settings)'."
        )
    if result.returncode != 0:
        raise PhoneError(output.decode(errors="replace").strip()[-300:] or "ADB command failed.")
    return result.stdout


def shell(command: str, timeout: float = 20) -> str:
    return run("shell", command, timeout=timeout).decode(errors="replace").strip()
