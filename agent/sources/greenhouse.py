"""Public Greenhouse board API: boards-api.greenhouse.io/v1/boards/<slug>/jobs"""
from ..models import Job
from .base import get


def fetch(cfg) -> list:
    jobs = []
    for slug in cfg.get("companies", []):
        resp = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if not resp:
            continue
        for e in resp.json().get("jobs", []):
            jobs.append(Job(
                title=e.get("title", ""),
                company=slug,
                url=e.get("absolute_url", ""),
                source="greenhouse",
                location=(e.get("location") or {}).get("name", ""),
                posted_at=(e.get("updated_at") or "")[:10],
            ))
    return jobs
