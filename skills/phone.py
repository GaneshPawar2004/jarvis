"""Phone skills: control the user's Android phone over ADB — open apps, read the screen,
tap, type, scroll and press keys."""
import re
import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from google.genai import types

from core import adb, confirm, vault
from core.adb import PhoneError
from skills import vision

APP_ALIASES = {
    "whatsapp": "com.whatsapp", "whatsapp business": "com.whatsapp.w4b",
    "instagram": "com.instagram.android", "insta": "com.instagram.android",
    "facebook": "com.facebook.katana", "messenger": "com.facebook.orca",
    "youtube": "com.google.android.youtube", "yt music": "com.google.android.apps.youtube.music",
    "chrome": "com.android.chrome", "gmail": "com.google.android.gm",
    "maps": "com.google.android.apps.maps", "google maps": "com.google.android.apps.maps",
    "google": "com.google.android.googlequicksearchbox", "photos": "com.google.android.apps.photos",
    "play store": "com.android.vending", "drive": "com.google.android.apps.docs",
    "gpay": "com.google.android.apps.nbu.paisa.user", "google pay": "com.google.android.apps.nbu.paisa.user",
    "phonepe": "com.phonepe.app", "paytm": "net.one97.paytm",
    "telegram": "org.telegram.messenger", "snapchat": "com.snapchat.android",
    "twitter": "com.twitter.android", "x": "com.twitter.android", "linkedin": "com.linkedin.android",
    "spotify": "com.spotify.music", "netflix": "com.netflix.mediaclient", "hotstar": "in.startv.hotstar",
    "amazon": "in.amazon.mShop.android.shopping", "flipkart": "com.flipkart.android",
    "zomato": "com.application.zomato", "swiggy": "in.swiggy.android",
}
INTENT_APPS = {  # built-in apps whose package differs per brand; open by intent instead
    "settings": "-a android.settings.SETTINGS",
    "camera": "-a android.media.action.STILL_IMAGE_CAMERA",
    "phone": "-a android.intent.action.DIAL", "dialer": "-a android.intent.action.DIAL",
    "contacts": "-a android.intent.action.VIEW -d content://contacts/people",
    "wifi settings": "-a android.settings.WIFI_SETTINGS",
    "bluetooth settings": "-a android.settings.BLUETOOTH_SETTINGS",
}
KEYS = {
    "back": 4, "home": 3, "recent apps": 187, "enter": 66, "search": 84, "delete": 67,
    "volume up": 24, "volume down": 25, "power": 26, "tab": 61, "menu": 82,
}
SHELL_SPECIAL = set("\\'\"`$&|;<>()[]{}*?!~#")

# Buttons whose tap needs the user's explicit yes, checked in code (not left to the AI).
RISKY = re.compile(
    r"\b(submit|send|pay|payment|post|apply|place order|buy|purchase|confirm|book|delete|remove|"
    r"transfer|checkout|proceed to pay|share|publish|sign up|register)\b",
    re.IGNORECASE,
)
SENSITIVE_WINDOW = 15 * 60  # seconds after typing an ID number during which screenshots need a yes

_elements: dict[int, dict] = {}  # element number -> {"point", "label"}, from the last screen read
_sensitive_typed_at = 0.0


def _packages() -> list[str]:
    return [p.removeprefix("package:") for p in adb.shell("pm list packages").splitlines()]


def phone_open_app(name: str) -> str:
    """Open an app on the user's Android phone.

    Args:
        name: The app's name, e.g. "LinkedIn", "WhatsApp", "camera", "settings", or an exact
            package name from phone_list_apps.
    """
    key = name.strip().lower()
    if key in INTENT_APPS:
        adb.shell(f"am start {INTENT_APPS[key]}")
        return f"Opened {name} on the phone."

    packages = _packages()
    package = APP_ALIASES.get(key) if APP_ALIASES.get(key) in packages else None
    if package is None and name in packages:
        package = name
    if package is None:
        squashed = re.sub(r"[^a-z0-9]", "", key)
        matches = [p for p in packages if squashed and squashed in p.lower().replace("_", "")]
        if len(matches) > 1:
            return f"Several apps match '{name}': {', '.join(matches[:8])}. Call again with the exact package name."
        package = matches[0] if matches else None
    if package is None:
        return f"No app matching '{name}' is installed. Use phone_list_apps to see what is installed."

    activity = adb.shell(
        f"cmd package resolve-activity --brief -c android.intent.category.LAUNCHER {package}"
    ).splitlines()[-1]
    if "/" not in activity:
        return f"{package} is installed but has no screen to open."
    adb.shell(f"am start -n {activity}")
    return f"Opened {package} on the phone."


def phone_list_apps() -> list[str]:
    """List the package names of apps the user installed on their phone."""
    return [p.removeprefix("package:") for p in adb.shell("pm list packages -3").splitlines()]


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    nums = [int(n) for n in re.findall(r"\d+", bounds)]
    if len(nums) != 4 or nums[2] <= nums[0] or nums[3] <= nums[1]:
        return None
    return (nums[0] + nums[2]) // 2, (nums[1] + nums[3]) // 2


def _label(node: ET.Element) -> str:
    own = node.get("text") or node.get("content-desc")
    if own:
        return own.strip()
    for child in node.iter():  # buttons often carry their text on a child
        text = child.get("text") or child.get("content-desc")
        if text:
            return text.strip()
    return node.get("resource-id", "").split("/")[-1].replace("_", " ")


def phone_read_screen() -> dict:
    """Read what is on the phone's screen as a numbered list of elements (buttons, text,
    input fields). Use the numbers with phone_tap and phone_type. Read again after each
    action to see the result."""
    raw = ""
    for _ in range(2):  # the dump fails while the screen is animating; retry once
        raw = adb.run("exec-out", "uiautomator dump /dev/tty", timeout=30).decode(errors="replace")
        if "<hierarchy" in raw:
            break
        time.sleep(1)
    if "<hierarchy" not in raw:
        return {"error": "Could not read the screen (it may be protected). Try phone_look_at_screen."}

    entries = vault.load()
    root = ET.fromstring(raw[raw.index("<?xml") if "<?xml" in raw else raw.index("<hierarchy"): raw.rindex(">") + 1])
    _elements.clear()
    items, seen, covered = [], set(), set()
    package = ""
    for node in root.iter("node"):
        package = package or node.get("package", "")
        center = _bounds_center(node.get("bounds", ""))
        if center is None or id(node) in covered:
            continue
        editable = node.get("class", "").endswith("EditText")
        clickable = node.get("clickable") == "true" or node.get("long-clickable") == "true"
        label = _label(node) if (clickable or editable) else (node.get("text") or node.get("content-desc") or "").strip()
        label = vault.redact(label, entries)  # the AI never sees the user's stored details
        if not label and not editable:
            continue
        if (label, center) in seen:
            continue
        seen.add((label, center))
        if clickable:  # its child labels are already summarised in this button
            covered.update(id(child) for child in node.iter() if not child.get("class", "").endswith("EditText"))
        number = len(_elements) + 1
        _elements[number] = {"point": center, "label": label}
        kind = "input" if editable else "button" if clickable else "text"
        entry = f"{number}. [{kind}] {label[:80]}"
        if editable and node.get("password") == "true":
            entry += " (password field)"
        items.append(entry)
        if number >= 120:
            break
    return {"app": package, "elements": items or ["(nothing readable on screen)"]}


def phone_look_at_screen(question: str) -> str:
    """Take a screenshot of the phone and answer a question about it visually. Use when
    phone_read_screen can't read something (images, games, protected screens).

    Args:
        question: What to find out, e.g. "What does this screen show?"
    """
    if time.time() - _sensitive_typed_at < SENSITIVE_WINDOW and not confirm.ask(
        "The phone screen may show ID numbers you just filled in. Send a screenshot to the AI anyway?"
    ):
        return "The user declined sending a screenshot. Use phone_read_screen instead."
    png = adb.run("exec-out", "screencap -p", timeout=30)
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return "Could not capture the phone screen (the app may block screenshots)."
    return vision._ask_gemini([
        vision._image_part(image),
        types.Part(text=f"This is a screenshot of the user's Android phone. Answer briefly in plain sentences.\n\nQuestion: {question}"),
    ])


def _element(element_number: int) -> dict:
    if element_number not in _elements:
        raise PhoneError(f"Element {element_number} is unknown. Call phone_read_screen first.")
    return _elements[element_number]


def _tap(element_number: int) -> None:
    x, y = _element(element_number)["point"]
    adb.shell(f"input tap {x} {y}")
    time.sleep(0.8)


def phone_tap(element_number: int) -> str:
    """Tap an element on the phone screen. Buttons like Submit, Send, Pay, Apply or Delete
    pop up a yes/no question to the user before tapping.

    Args:
        element_number: The element's number from the latest phone_read_screen.
    """
    label = _element(element_number)["label"]
    if RISKY.search(label) and not confirm.ask(f"JARVIS wants to tap '{label}' on your phone. Allow?"):
        return f"The user did NOT allow tapping '{label}'. Do not retry unless they ask again."
    _tap(element_number)
    return f"Tapped '{label}'."


def phone_fill_field(element_number: int, field_key: str) -> str:
    """Fill an input field on the phone with one of the user's saved details from the vault.
    The real value is typed locally and never shown to you. Use vault_list_fields to see
    which field keys exist.

    Args:
        element_number: The input field's number from the latest phone_read_screen.
        field_key: The vault key to fill in, e.g. "email", "full_name", "pincode".
    """
    global _sensitive_typed_at
    entry = vault.load().get(field_key)
    if entry is None:
        return f"'{field_key}' is not in the vault. Ask the user for it, or check vault_list_fields."
    if entry["sensitive"] and not confirm.ask(f"Fill your {entry['label']} into the form on your phone?"):
        return f"The user did NOT allow filling their {entry['label']}."
    if not entry["value"].isascii():
        return f"The saved {entry['label']} has non-English characters, which the phone bridge can't type yet."
    _tap(element_number)
    adb.shell("input keycombination 113 29")  # Ctrl+A, then delete: clear anything already there
    adb.shell("input keyevent 67")
    _input_text(entry["value"])
    if entry["sensitive"]:
        _sensitive_typed_at = time.time()
    return f"Filled the field with the user's {entry['label']}."


def _input_text(text: str) -> None:
    escaped = "".join("\\" + c if c in SHELL_SPECIAL else c for c in text).replace(" ", "%s")
    adb.shell(f"input text {escaped}")


def phone_type(text: str, element_number: int = 0) -> str:
    """Type text on the phone, optionally into a specific input field first.

    Args:
        text: The text to type (English letters, numbers and common symbols).
        element_number: Input field number from phone_read_screen to tap first; 0 types into the focused field.
    """
    if not text.isascii():
        return "The phone keyboard bridge can only type English characters for now."
    if element_number:
        _tap(element_number)
    _input_text(text)
    return f"Typed {len(text)} characters on the phone."


def phone_press(key: str) -> str:
    """Press a button on the phone.

    Args:
        key: One of "back", "home", "recent apps", "enter", "search", "delete", "volume up",
            "volume down", "tab".
    """
    code = KEYS.get(key.strip().lower())
    if code is None:
        return f"Unknown key '{key}'."
    adb.shell(f"input keyevent {code}")
    time.sleep(0.5)
    return f"Pressed {key}."


def phone_scroll(direction: str) -> str:
    """Scroll the phone screen.

    Args:
        direction: "down" (see content further down), "up", "left" or "right".
    """
    size = re.findall(r"(\d+)x(\d+)", adb.shell("wm size"))[-1]
    w, h = int(size[0]), int(size[1])
    moves = {
        "down": (w // 2, h * 3 // 4, w // 2, h // 4),
        "up": (w // 2, h // 4, w // 2, h * 3 // 4),
        "left": (w * 4 // 5, h // 2, w // 5, h // 2),
        "right": (w // 5, h // 2, w * 4 // 5, h // 2),
    }
    move = moves.get(direction.strip().lower())
    if move is None:
        return "Direction must be up, down, left or right."
    adb.shell("input swipe {} {} {} {} 350".format(*move))
    time.sleep(0.6)
    return f"Scrolled {direction}."


def phone_status() -> dict:
    """Get the phone's battery level, charging state and the app currently on screen."""
    battery = adb.shell("dumpsys battery")
    level = re.search(r"level: (\d+)", battery)
    charging = re.search(r"status: (\d+)", battery)
    top = re.search(r"topResumedActivity=.*? (\S+)/", adb.shell("dumpsys activity activities | grep topResumedActivity"))
    return {
        "battery_percent": int(level.group(1)) if level else None,
        "charging": charging.group(1) in ("2", "5") if charging else None,
        "app_on_screen": top.group(1) if top else "unknown",
    }
