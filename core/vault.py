"""Encrypted vault for the user's personal details, protected with Windows DPAPI (only this
Windows user on this PC can decrypt it). Values are never sent to the AI model: it only
sees field names, and tools type the real values locally."""
import ctypes
import json
import re
from ctypes import wintypes

import config

VAULT_FILE = config.DATA_DIR / "vault.bin"
_ENTROPY = b"JARVIS-vault-v1"

# Suggested fields: key -> (label, category, sensitive)
TEMPLATE = {
    "full_name": ("Full name", "Basic", False),
    "first_name": ("First name", "Basic", False),
    "last_name": ("Last name", "Basic", False),
    "email": ("Email", "Basic", False),
    "phone": ("Mobile number", "Basic", False),
    "date_of_birth": ("Date of birth (DD/MM/YYYY)", "Basic", False),
    "gender": ("Gender", "Basic", False),
    "father_name": ("Father's name", "Basic", False),
    "address_line1": ("Address line 1", "Address", False),
    "address_line2": ("Address line 2", "Address", False),
    "city": ("City", "Address", False),
    "state": ("State", "Address", False),
    "pincode": ("PIN code", "Address", False),
    "country": ("Country", "Address", False),
    "job_title": ("Current job title", "Work", False),
    "company": ("Current company", "Work", False),
    "experience_years": ("Years of experience", "Work", False),
    "skills": ("Skills", "Work", False),
    "linkedin_url": ("LinkedIn profile URL", "Work", False),
    "portfolio_url": ("Portfolio / GitHub URL", "Work", False),
    "college": ("College / university", "Education", False),
    "degree": ("Degree", "Education", False),
    "branch": ("Branch / specialisation", "Education", False),
    "graduation_year": ("Graduation year", "Education", False),
    "cgpa": ("CGPA / percentage", "Education", False),
    "pan_number": ("PAN number", "IDs", True),
    "aadhaar_number": ("Aadhaar number", "IDs", True),
    "passport_number": ("Passport number", "IDs", True),
    "driving_licence": ("Driving licence number", "IDs", True),
    "voter_id": ("Voter ID", "IDs", True),
}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _crypt(data: bytes, encrypt: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    source, entropy, out = _blob(data), _blob(_ENTROPY), _Blob()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    description = "JARVIS vault" if encrypt else None
    if not fn(ctypes.byref(source), description, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def load() -> dict[str, dict]:
    """{key: {"value", "label", "category", "sensitive"}}"""
    if not VAULT_FILE.exists():
        return {}
    return json.loads(_crypt(VAULT_FILE.read_bytes(), encrypt=False).decode("utf-8"))


def save(entries: dict[str, dict]) -> None:
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    VAULT_FILE.write_bytes(_crypt(json.dumps(entries, ensure_ascii=False).encode("utf-8"), encrypt=True))


def set_field(key: str, value: str, label: str = "", category: str = "Custom", sensitive: bool = False) -> None:
    label_t, category_t, sensitive_t = TEMPLATE.get(key, (label or key.replace("_", " ").capitalize(), category, sensitive))
    entries = load()
    entries[key] = {"value": value, "label": label or label_t, "category": category_t, "sensitive": sensitive or sensitive_t}
    save(entries)


def delete_field(key: str) -> bool:
    entries = load()
    if entries.pop(key, None) is None:
        return False
    save(entries)
    return True


def mask(value: str) -> str:
    """For display to the user: 'ABCDE1234F' -> 'AB******4F'."""
    if len(value) <= 4:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def redact(text: str, entries: dict[str, dict] | None = None) -> str:
    """Replace any vault value inside text with a placeholder, before the AI sees it."""
    entries = load() if entries is None else entries
    for entry in sorted(entries.values(), key=lambda e: -len(e["value"])):
        if len(entry["value"]) >= 3:
            placeholder = f"[your {entry['label']}]"
            text = re.sub(re.escape(entry["value"]), lambda _: placeholder, text, flags=re.IGNORECASE)
    return text
