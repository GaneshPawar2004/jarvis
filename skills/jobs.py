"""Job-hunting skills: search Naukri and LinkedIn for real job posts, match them to the user's
resume, and keep a shortlist / application tracker."""
import re

from ddgs import DDGS

import config
from core import db, resume

SOURCES = {
    "naukri": ("site:naukri.com", re.compile(r"naukri\.com/job-listings-")),
    "linkedin": ("site:linkedin.com/jobs/view", re.compile(r"linkedin\.com/jobs/view/")),
}
STATUSES = ("shortlisted", "applied", "skipped", "interview", "rejected", "offer")


def get_resume_profile() -> dict | str:
    """Get the user's full resume profile (experience, skills, education, projects, suggested
    roles and locations) to match jobs or answer questions about their background."""
    profile = resume.latest()
    if profile is None:
        return "No resume uploaded yet. Ask the user to upload it in the JARVIS phone app (MY DETAILS → UPLOAD RESUME)."
    return {k: v for k, v in profile.items() if k not in ("email", "phone")}


def find_jobs(role: str, location: str, sources: str = "naukri,linkedin") -> list[dict] | str:
    """Search Naukri and LinkedIn for recent real job posts. Run it for the roles and places
    that suit the user's resume, then judge each result against their profile yourself.

    Args:
        role: Job title to search for, e.g. "Python developer".
        location: City or "Remote", e.g. "Pune".
        sources: Which sites, comma-separated: "naukri", "linkedin" or "naukri,linkedin".
    """
    found, seen = [], set()
    for name in [s.strip().lower() for s in sources.split(",") if s.strip().lower() in SOURCES]:
        site, is_job_post = SOURCES[name]
        for query in (f"{role} {location} {site}", f"{role} jobs in {location} {site}"):
            try:
                results = DDGS().text(query, max_results=15, timelimit="m")
            except Exception:
                continue
            for r in results:
                url = r["href"].split("?")[0]
                if is_job_post.search(url) and url not in seen:
                    seen.add(url)
                    found.append({"source": name, "title": r["title"][:140], "url": url, "snippet": r["body"][:300]})
    if not found:
        return f"No recent {role} posts found in {location}. Try a related role or nearby city."
    return found[:25]


def shortlist_job(title: str, company: str, location: str, url: str, reason: str) -> str:
    """Save a job to the user's shortlist, with why it suits them.

    Args:
        title: Job title.
        company: Company name.
        location: Job location.
        url: Link to the job post.
        reason: One line on why it matches the user's resume.
    """
    if db.rows("SELECT id FROM jobs WHERE url = ?", (url,)):
        return "Already on the shortlist."
    source = "linkedin" if "linkedin.com" in url else "naukri" if "naukri.com" in url else "web"
    db.execute(
        "INSERT INTO jobs (title, company, location, url, source, reason, status, saved) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (title, company, location, url, source, reason, "shortlisted", config.now().isoformat(timespec="seconds")),
    )
    return f"Shortlisted {title} at {company}."


def list_jobs(status: str = "") -> list[dict] | str:
    """List the user's saved jobs (shortlist and application tracker), newest first.

    Args:
        status: Optional filter: "shortlisted", "applied", "skipped", "interview", "rejected" or "offer". Empty for all.
    """
    sql = "SELECT id, title, company, location, url, reason, status, saved FROM jobs"
    rows = db.rows(sql + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT 50", (status,) if status else ())
    if not rows:
        return "No saved jobs yet."
    keys = ("id", "title", "company", "location", "url", "reason", "status", "saved")
    return [dict(zip(keys, r)) for r in rows]


def update_job_status(job_id: int, status: str) -> str:
    """Record what happened with a saved job, e.g. after the user applies.

    Args:
        job_id: The job's id from list_jobs.
        status: One of "shortlisted", "applied", "skipped", "interview", "rejected", "offer".
    """
    if status not in STATUSES:
        return f"Status must be one of: {', '.join(STATUSES)}."
    if not db.rows("SELECT id FROM jobs WHERE id = ?", (job_id,)):
        return f"No saved job with id {job_id}."
    db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    return f"Job {job_id} marked as {status}."
