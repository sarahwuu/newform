"""Public Lever postings API: api.lever.co/v0/postings/<slug>?mode=json"""
from datetime import datetime, timezone

from ..models import Job
from .base import get


def fetch(cfg) -> list:
    jobs = []
    for slug in cfg.get("companies", []):
        resp = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not resp:
            continue
        for e in resp.json():
            created = e.get("createdAt")
            jobs.append(Job(
                title=e.get("text", ""),
                company=slug,
                url=e.get("hostedUrl", ""),
                source="lever",
                location=(e.get("categories") or {}).get("location", ""),
                posted_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat() if created else "",
            ))
    return jobs
