"""Public Ashby job board API: api.ashbyhq.com/posting-api/job-board/<slug>"""
from ..models import Job
from .base import get


def fetch(cfg) -> list:
    jobs = []
    for slug in cfg.get("companies", []):
        resp = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if not resp:
            continue
        for e in resp.json().get("jobs", []):
            if not e.get("isListed", True):
                continue
            jobs.append(Job(
                title=e.get("title", ""),
                company=slug,
                url=e.get("jobUrl") or e.get("applyUrl", ""),
                source="ashby",
                location=e.get("location", ""),
                posted_at=(e.get("publishedAt") or "")[:10],
            ))
    return jobs
