"""The user's resume: Gemini reads the PDF once into a structured profile that JARVIS keeps
in its memory, so it can match jobs and fill applications."""
import json

from google.genai import types

import config
from core import db, llm

MAX_BYTES = 8 * 1024 * 1024

EXTRACT_PROMPT = """Read this resume and return ONLY a JSON object with these keys (use null or []
when something isn't in the resume; never invent anything):
{
 "full_name": str, "first_name": str, "last_name": str, "email": str, "phone": str,
 "city": str, "state": str, "linkedin_url": str, "portfolio_url": str,
 "headline": str (one line, e.g. "Python backend developer, 2 years"),
 "total_experience_years": number,
 "current_job_title": str, "current_company": str,
 "skills": [str],
 "experience": [{"title": str, "company": str, "from": str, "to": str, "highlights": [str]}],
 "education": [{"degree": str, "branch": str, "institution": str, "year": str, "score": str}],
 "projects": [{"name": str, "summary": str, "tech": [str]}],
 "certifications": [str],
 "suggested_roles": [str] (3-6 job titles this person fits, most suitable first),
 "suggested_locations": [str] (from the resume, e.g. their city, plus "Remote" if suitable),
 "summary_for_jarvis": str (5-8 short lines: who they are, strengths, experience level, what
     roles suit them; written so an assistant can match jobs; no contact details)
}"""


def extract(pdf: bytes) -> dict:
    """Ask Gemini to read the resume PDF into a profile."""
    response, _ = llm.generate(
        [types.Content(role="user", parts=[
            types.Part.from_bytes(data=pdf, mime_type="application/pdf"),
            types.Part(text=EXTRACT_PROMPT),
        ])],
        types.GenerateContentConfig(response_mime_type="application/json"),
    )
    profile = json.loads(response.text or "{}")
    if not isinstance(profile, dict) or not (profile.get("summary_for_jarvis") or profile.get("skills")):
        raise ValueError("That file doesn't look like a resume I can read.")
    return profile


def save(filename: str, pdf: bytes) -> dict:
    if len(pdf) > MAX_BYTES:
        raise ValueError("The resume is too large (max 8 MB).")
    if not pdf.startswith(b"%PDF"):
        raise ValueError("Please upload the resume as a PDF.")
    profile = extract(pdf)
    db.execute(
        "INSERT INTO resumes (filename, uploaded, data, profile) VALUES (?, ?, ?, ?)",
        (filename[:120] or "resume.pdf", config.now().isoformat(timespec="seconds"), pdf, json.dumps(profile)),
    )
    return profile


def latest() -> dict | None:
    rows = db.rows("SELECT profile, uploaded FROM resumes ORDER BY id DESC LIMIT 1")
    if not rows:
        return None
    profile = json.loads(rows[0][0])
    profile["resume_uploaded"] = rows[0][1]
    return profile


def summary() -> str:
    """Short profile text for JARVIS's system prompt."""
    profile = latest()
    if not profile:
        return "(no resume uploaded yet; the user can upload one in the phone app: MY DETAILS)"
    skills = ", ".join((profile.get("skills") or [])[:20])
    roles = ", ".join(profile.get("suggested_roles") or [])
    return (f"{profile.get('summary_for_jarvis', '').strip()}\nSkills: {skills}\n"
            f"Suits roles: {roles}\n(Resume uploaded {profile['resume_uploaded'][:10]}; "
            "call get_resume_profile for full details.)")


VAULT_KEYS = {  # resume field -> vault key, for "add these to My details?"
    "full_name": "full_name", "first_name": "first_name", "last_name": "last_name", "email": "email",
    "phone": "phone", "city": "city", "state": "state", "linkedin_url": "linkedin_url",
    "portfolio_url": "portfolio_url", "current_job_title": "job_title", "current_company": "company",
    "total_experience_years": "experience_years",
}


def vault_suggestions(profile: dict) -> dict[str, str]:
    """Details the phone app can offer to save into its vault (the user picks which)."""
    out = {VAULT_KEYS[k]: str(v) for k, v in profile.items() if k in VAULT_KEYS and v not in (None, "", [])}
    if profile.get("skills"):
        out["skills"] = ", ".join(profile["skills"][:25])
    education = (profile.get("education") or [{}])[0] or {}
    for src, key in (("institution", "college"), ("degree", "degree"), ("branch", "branch"),
                     ("year", "graduation_year"), ("score", "cgpa")):
        if education.get(src):
            out[key] = str(education[src])
    return out
