"""Generates an application draft for each new job.

With ANTHROPIC_API_KEY set, drafts are AI-tailored to your profile using
Claude. Without it, a checklist-style template draft is written instead so
the pipeline still works end to end.
"""
import os
import re
from pathlib import Path

import yaml

PROFILE_PATH = Path("profile.yaml")
DRAFTS_DIR = Path("drafts")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def load_profile() -> dict:
    if PROFILE_PATH.exists():
        return yaml.safe_load(PROFILE_PATH.read_text()) or {}
    return {}


def _resume_text() -> str:
    pdf = Path("materials/resume.pdf")
    if not pdf.exists():
        return ""
    try:
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(pdf).pages)[:6000]
    except Exception as e:
        print(f"  [warn] could not read resume.pdf: {type(e).__name__}")
        return ""


def _template_draft(job, profile) -> str:
    return f"""# {job.title} — {job.company}

**Apply here:** {job.url}
**Location:** {job.location or "see posting"}
**Found via:** {job.source} on {job.posted_at or "unknown date"}

_(Set the ANTHROPIC_API_KEY secret to get AI-tailored drafts here.)_

## Before you submit
- [ ] Resume PDF attached (materials/resume.pdf)
- [ ] Portfolio link ready: {profile.get("portfolio") or "ADD YOUR PORTFOLIO URL to profile.yaml"}
- [ ] Short "why this company" answer drafted
- [ ] Availability: graduating {profile.get("graduation", "May 2027")} — confirm the term matches {job.terms or "the posting"}
"""


def _ai_draft(job, profile, resume: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    prompt = f"""You are helping a design student apply to a job the moment it was posted.

CANDIDATE PROFILE (yaml):
{yaml.safe_dump(profile)}

RESUME TEXT (may be empty):
{resume or "(not provided)"}

JOB:
- Title: {job.title}
- Company: {job.company}
- Location: {job.location}
- Apply URL: {job.url}

Write an application prep document in markdown with exactly these sections:
1. **Pitch** — a 3-4 sentence tailored "about me" the candidate can paste into an application form, specific to this company and role. No fluff, no invented facts; if the profile lacks a detail, leave a [FILL IN: ...] placeholder.
2. **Why {job.company}** — 2-3 sentences answering the classic "why do you want to work here" question, grounded in what this company is known for.
3. **Resume emphasis** — 3-5 bullets on which experiences/skills from the profile/resume to emphasize for this specific role.
4. **Short-answer bank** — brief suggested answers for: preferred start date/term (graduating {profile.get("graduation", "May 2027")}), work authorization, and portfolio link.
5. **Speed checklist** — the 3 fastest steps to submit a strong application today.

Be concrete and honest. Never fabricate experience."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system="You write concise, honest job application materials for a design student. Markdown only.",
        messages=[{"role": "user", "content": prompt}],
    )
    body = "".join(b.text for b in response.content if b.type == "text")
    header = (f"# {job.title} — {job.company}\n\n"
              f"**Apply here:** {job.url}\n"
              f"**Location:** {job.location or 'see posting'}\n"
              f"**Found via:** {job.source} on {job.posted_at or 'unknown date'}\n\n---\n\n")
    return header + body


def write_draft(job, profile, use_ai: bool, resume: str) -> Path:
    DRAFTS_DIR.mkdir(exist_ok=True)
    path = DRAFTS_DIR / f"{_slug(job.company)}--{_slug(job.title)}.md"
    if use_ai:
        try:
            path.write_text(_ai_draft(job, profile, resume))
            return path
        except Exception as e:
            print(f"  [warn] AI draft failed for {job.title}: {type(e).__name__}: {e}")
    path.write_text(_template_draft(job, profile))
    return path
