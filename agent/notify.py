"""Email alerts for new jobs.

Primary channel: SMTP email (Gmail app password works out of the box).
Fallback: if SMTP isn't configured but we're running inside GitHub Actions,
open a GitHub Issue — GitHub then emails you its notification. That way
alerts work from day one, before any secrets are set.
"""
import json
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText


def _job_lines_html(jobs) -> str:
    rows = []
    for j in jobs:
        rows.append(
            f'<li><a href="{j.url}"><b>{j.title}</b></a> — {j.company}'
            f'{" · " + j.location if j.location else ""}'
            f'{" · posted " + j.posted_at if j.posted_at else ""} <i>({j.source})</i></li>'
        )
    return "<ul>" + "\n".join(rows) + "</ul>"


def _job_lines_md(jobs) -> str:
    return "\n".join(
        f"- [**{j.title}**]({j.url}) — {j.company}"
        f"{' · ' + j.location if j.location else ''}"
        f"{' · posted ' + j.posted_at if j.posted_at else ''} _({j.source})_"
        for j in jobs
    )


def send_email(jobs, drafts) -> bool:
    user, password = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (user and password):
        return False
    to = os.getenv("EMAIL_TO", user)
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))

    n = len(jobs)
    subject = f"🎯 {n} new design {'internship' if n == 1 else 'internships/roles'} just dropped"
    repo = os.getenv("GITHUB_REPOSITORY", "")
    drafts_note = (
        f'<p>Tailored application drafts are in the <a href="https://github.com/{repo}/tree/main/drafts">drafts folder</a>.</p>'
        if repo else "<p>Tailored application drafts are in the repo's <code>drafts/</code> folder.</p>"
    )
    html = f"<h2>New roles matching your search</h2>{_job_lines_html(jobs)}{drafts_note}<p>Apply fast — early applications get seen.</p>"

    msg = MIMEText(html, "html")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.sendmail(user, [to], msg.as_string())
    print(f"  emailed {to}: {n} job(s)")
    return True


def open_github_issue(jobs) -> bool:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (token and repo):
        return False
    n = len(jobs)
    body = {
        "title": f"🎯 {n} new design {'role' if n == 1 else 'roles'} dropped",
        "body": _job_lines_md(jobs) + "\n\nDrafts are in `drafts/`. Close this issue once you've applied.",
        "labels": ["job-alert"],
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"  opened GitHub issue ({resp.status}) — GitHub will email you")
    return True


def notify(jobs, drafts) -> None:
    try:
        if send_email(jobs, drafts):
            return
    except Exception as e:
        print(f"  [warn] email failed: {type(e).__name__}: {e}")
    try:
        if open_github_issue(jobs):
            return
    except Exception as e:
        print(f"  [warn] github issue failed: {type(e).__name__}: {e}")
    print("  [warn] no notification channel configured (set SMTP_USER/SMTP_PASS secrets)")
