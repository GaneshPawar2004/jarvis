"""PC control skills: volume, brightness, screenshots, typing, shortcuts and media keys."""
import time
from datetime import datetime
from pathlib import Path

import mss
import mss.tools
import pyautogui
import pyperclip
import screen_brightness_control as sbc
from pycaw.pycaw import AudioUtilities

SCREENSHOT_DIR = Path.home() / "Pictures" / "JARVIS Screenshots"
KEY_ALIASES = {"windows": "win", "control": "ctrl", "escape": "esc", "return": "enter", "del": "delete"}
MEDIA_KEYS = {"play": "playpause", "pause": "playpause", "play_pause": "playpause",
              "next": "nexttrack", "previous": "prevtrack", "stop": "stop"}

pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort typing


def _volume():
    return AudioUtilities.GetSpeakers().EndpointVolume


def set_volume(level: int) -> str:
    """Set the computer's speaker volume.

    Args:
        level: Volume from 0 to 100.
    """
    level = max(0, min(100, level))
    endpoint = _volume()
    endpoint.SetMute(0, None)
    endpoint.SetMasterVolumeLevelScalar(level / 100, None)
    return f"Volume set to {level}%."


def change_volume(amount: int) -> str:
    """Turn the volume up or down relative to its current level.

    Args:
        amount: Percentage points to change by; positive is louder, negative is quieter (e.g. 10 or -20).
    """
    current = round(_volume().GetMasterVolumeLevelScalar() * 100)
    return set_volume(current + amount).replace("set to", f"changed from {current}% to")


def mute_audio(mute: bool) -> str:
    """Mute or unmute the computer's sound.

    Args:
        mute: True to mute, False to unmute.
    """
    _volume().SetMute(1 if mute else 0, None)
    return "Sound muted." if mute else "Sound unmuted."


def set_brightness(level: int) -> str:
    """Set the laptop screen brightness.

    Args:
        level: Brightness from 0 to 100.
    """
    level = max(0, min(100, level))
    sbc.set_brightness(level)
    return f"Brightness set to {level}%."


def change_brightness(amount: int) -> str:
    """Make the screen brighter or dimmer relative to its current level.

    Args:
        amount: Percentage points to change by; positive is brighter, negative is dimmer.
    """
    current = sbc.get_brightness()[0]
    return set_brightness(current + amount).replace("set to", f"changed from {current}% to")


def take_screenshot() -> str:
    """Take a screenshot of the whole screen and save it to the Pictures folder."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
    with mss.mss() as screen:
        shot = screen.grab(screen.monitors[0])
        mss.tools.to_png(shot.rgb, shot.size, output=str(path))
    return f"Screenshot saved to {path}"


def type_text(text: str) -> str:
    """Type text into whichever window is currently focused, as if using the keyboard.
    To type into a particular app, open it first with open_application.

    Args:
        text: The text to type. Use \\n for a new line.
    """
    time.sleep(0.5)  # let a just-opened app take focus
    if text.isascii() and len(text) <= 20:
        pyautogui.write(text, interval=0.005)
    else:  # long or non-English text: paste it in one go (instant), then restore the clipboard
        previous = pyperclip.paste()
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyperclip.copy(previous)
    return f"Typed {len(text)} characters."


def press_keys(keys: str) -> str:
    """Press a key or keyboard shortcut in the focused window, e.g. "enter", "ctrl+s",
    "alt+tab", "win+d" (show desktop), "ctrl+shift+esc".

    Args:
        keys: Key names joined with "+".
    """
    names = [KEY_ALIASES.get(k.strip().lower(), k.strip().lower()) for k in keys.split("+")]
    unknown = [k for k in names if k not in pyautogui.KEYBOARD_KEYS]
    if unknown:
        return f"Unknown key name(s): {', '.join(unknown)}"
    time.sleep(0.3)
    pyautogui.hotkey(*names)
    return f"Pressed {'+'.join(names)}."


def media_control(action: str) -> str:
    """Control music or video playing on the computer (Spotify, YouTube, etc.).

    Args:
        action: One of "play", "pause", "next", "previous", "stop".
    """
    key = MEDIA_KEYS.get(action.strip().lower())
    if key is None:
        return f"Unknown media action '{action}'. Use play, pause, next, previous or stop."
    pyautogui.press(key)
    return f"Media: {action}."
