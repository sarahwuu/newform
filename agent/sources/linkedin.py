"""LinkedIn public (guest) job search. No login; parses the HTML job cards
that power the logged-out search page. Rate limits are common — failures
are logged and skipped.
"""
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..models import Job
from .base import get

SEARCH = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
          "?keywords={kw}&location={loc}&f_TPR=r{secs}&start=0")


def fetch(cfg) -> list:
    jobs = []
    loc = quote(cfg.get("location", "United States"))
    secs = int(cfg.get("hours_back", 24)) * 3600
    for q in cfg.get("queries", []):
        resp = get(SEARCH.format(kw=quote(q), loc=loc, secs=secs), timeout=20)
        if not resp:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for card in soup.select("div.base-card, li"):
            title_el = card.select_one("h3.base-search-card__title")
            link_el = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']")
            if not title_el or not link_el:
                continue
            company_el = card.select_one("h4.base-search-card__subtitle")
            loc_el = card.select_one("span.job-search-card__location")
            time_el = card.select_one("time")
            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "",
                url=link_el["href"].split("?")[0],
                source="linkedin",
                location=loc_el.get_text(strip=True) if loc_el else "",
                posted_at=time_el.get("datetime", "") if time_el else "",
            ))
    return jobs
