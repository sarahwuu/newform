"""SimplifyJobs community lists (internships + new grad), served as raw JSON."""
from datetime import datetime, timezone

from ..models import Job
from .base import get


def fetch(cfg) -> list:
    jobs = []
    for url in cfg.get("urls", []):
        resp = get(url)
        if not resp:
            continue
        for e in resp.json():
            if not e.get("active", False) or not e.get("is_visible", True):
                continue
            posted = e.get("date_posted")
            jobs.append(Job(
                title=e.get("title", ""),
                company=e.get("company_name", ""),
                url=e.get("url", ""),
                source="github-list",
                location="; ".join(e.get("locations", [])),
                posted_at=datetime.fromtimestamp(posted, tz=timezone.utc).date().isoformat() if posted else "",
                terms=[t for t in e.get("terms") or [] if t != "N/A"],
            ))
    return jobs
