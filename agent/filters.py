import re


def _word_match(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase.lower())}(?![a-z0-9])", text.lower()) is not None


def matches(job, cfg) -> bool:
    title = job.title.lower()

    kw = cfg["keywords"]
    if not any(_word_match(title, p) for p in kw["include"]):
        return False
    if any(_word_match(title, p) for p in kw.get("exclude", [])):
        return False
    if any(p.lower() in title for p in cfg.get("seniority_exclude", [])):
        return False

    level = cfg.get("level", {})
    if level.get("require", True):
        haystack = f"{title} {' '.join(job.terms).lower()}"
        if not any(_word_match(haystack, p) for p in level["include"]):
            return False
    return True
