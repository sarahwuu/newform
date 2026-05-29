#!/usr/bin/env python3
"""
Trump Stock Alert Monitor
Polls Truth Social + White House statements for company/ticker mentions
and sends an email alert with context.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import feedparser
import requests

from companies import COMPANIES, LOOKUP

# ---------------------------------------------------------------------------
# Config from environment variables (set as GitHub Actions secrets)
# ---------------------------------------------------------------------------
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", GMAIL_USER)
STATE_FILE = Path(__file__).parent / "seen_posts.json"

# Truth Social Mastodon-compatible API (no auth required for public accounts)
TRUTH_SOCIAL_LOOKUP = "https://truthsocial.com/api/v1/accounts/lookup"
TRUTH_SOCIAL_STATUSES = "https://truthsocial.com/api/v1/accounts/{}/statuses"

# Official White House briefing room RSS
WHITEHOUSE_RSS = "https://www.whitehouse.gov/briefing-room/feed/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrumpStockAlertBot/1.0)"
}

REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"seen_truth": [], "seen_wh": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Company/ticker detection
# ---------------------------------------------------------------------------

# Match bare uppercase tickers like $PLTR or PLTR (2-5 letters surrounded by non-alpha)
TICKER_RE = re.compile(r'(?<![A-Za-z])\$?([A-Z]{1,5})(?![A-Za-z])')


def find_companies(text: str) -> list[tuple[str, str]]:
    """Returns list of (ticker, matched_term) found in text."""
    hits: dict[str, str] = {}

    # 1. Check full ticker/name/alias dictionary (case-insensitive substring)
    text_lower = text.lower()
    for term, ticker in LOOKUP.items():
        pattern = r'(?<![a-z])' + re.escape(term) + r'(?![a-z])'
        if re.search(pattern, text_lower):
            if ticker not in hits:
                hits[ticker] = term

    # 2. Bare uppercase tickers in original text (e.g. $PLTR or "buy PLTR")
    for m in TICKER_RE.finditer(text):
        candidate = m.group(1)
        if candidate in COMPANIES and candidate not in hits:
            hits[candidate] = m.group(0)

    return [(ticker, term) for ticker, term in hits.items()]


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def get_truth_social_account_id() -> Optional[str]:
    try:
        resp = requests.get(
            TRUTH_SOCIAL_LOOKUP,
            params={"acct": "realDonaldTrump"},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        print(f"[Truth Social] Could not fetch account ID: {e}")
        return None


def fetch_truth_social_posts(account_id: str) -> list[dict]:
    try:
        resp = requests.get(
            TRUTH_SOCIAL_STATUSES.format(account_id),
            params={"limit": 20},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        posts = resp.json()
        return [
            {
                "id": p["id"],
                "text": re.sub(r"<[^>]+>", " ", p.get("content", "")),
                "url": p.get("url", ""),
                "created_at": p.get("created_at", ""),
                "source": "Truth Social",
            }
            for p in posts
            if isinstance(p, dict)
        ]
    except Exception as e:
        print(f"[Truth Social] Could not fetch posts: {e}")
        return []


def fetch_whitehouse_posts() -> list[dict]:
    try:
        feed = feedparser.parse(WHITEHOUSE_RSS)
        posts = []
        for entry in feed.entries[:20]:
            text = entry.get("summary", "") or entry.get("title", "")
            text = re.sub(r"<[^>]+>", " ", text)
            posts.append({
                "id": entry.get("id") or entry.get("link", ""),
                "text": entry.get("title", "") + " " + text,
                "url": entry.get("link", ""),
                "created_at": entry.get("published", ""),
                "source": "White House",
            })
        return posts
    except Exception as e:
        print(f"[White House] Could not fetch feed: {e}")
        return []


# ---------------------------------------------------------------------------
# Email alert
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print(f"[Email] Credentials not set — would have sent: {subject}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ALERT_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())
        print(f"[Email] Sent: {subject}")
    except Exception as e:
        print(f"[Email] Failed to send: {e}")
        sys.exit(1)


def build_email(post: dict, companies: list[tuple[str, str]]) -> tuple[str, str]:
    tickers = ", ".join(f"${t}" for t, _ in companies)
    names = ", ".join(COMPANIES[t][0] for t, _ in companies)

    subject = f"Trump mentioned {tickers} — potential stock move"

    rows = "".join(
        f"<tr><td style='padding:4px 8px;font-weight:bold'>${t}</td>"
        f"<td style='padding:4px 8px'>{COMPANIES[t][0]}</td>"
        f"<td style='padding:4px 8px;color:#888'>matched: \"{m}\"</td></tr>"
        for t, m in companies
    )

    html = f"""
<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
<h2 style="color:#c0392b">Trump Mentioned {names}</h2>
<p><b>Source:</b> {post['source']}<br>
<b>Time:</b> {post['created_at']}<br>
<a href="{post['url']}">View original post</a></p>

<div style="background:#f8f9fa;border-left:4px solid #c0392b;padding:12px 16px;margin:16px 0">
  <pre style="white-space:pre-wrap;font-size:14px">{post['text'].strip()}</pre>
</div>

<h3>Detected companies</h3>
<table style="border-collapse:collapse;width:100%">
  <tr style="background:#f0f0f0">
    <th style="padding:4px 8px;text-align:left">Ticker</th>
    <th style="padding:4px 8px;text-align:left">Company</th>
    <th style="padding:4px 8px;text-align:left">Matched term</th>
  </tr>
  {rows}
</table>

<p style="color:#888;font-size:12px;margin-top:24px">
  This is an automated alert. Not financial advice. Verify before trading.
</p>
</body></html>
"""
    return subject, html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    state = load_state()
    alerts_sent = 0

    # --- Truth Social ---
    account_id = get_truth_social_account_id()
    if account_id:
        ts_posts = fetch_truth_social_posts(account_id)
        print(f"[Truth Social] Fetched {len(ts_posts)} posts")
        for post in ts_posts:
            if post["id"] in state["seen_truth"]:
                continue
            state["seen_truth"].append(post["id"])
            companies = find_companies(post["text"])
            if companies:
                print(f"[Truth Social] Match! {[t for t,_ in companies]} in: {post['text'][:80]}")
                subject, html = build_email(post, companies)
                send_email(subject, html)
                alerts_sent += 1

    state["seen_truth"] = state["seen_truth"][-500:]

    # --- White House ---
    wh_posts = fetch_whitehouse_posts()
    print(f"[White House] Fetched {len(wh_posts)} items")
    for post in wh_posts:
        if post["id"] in state["seen_wh"]:
            continue
        state["seen_wh"].append(post["id"])
        companies = find_companies(post["text"])
        if companies:
            print(f"[White House] Match! {[t for t,_ in companies]} in: {post['text'][:80]}")
            subject, html = build_email(post, companies)
            send_email(subject, html)
            alerts_sent += 1

    state["seen_wh"] = state["seen_wh"][-500:]

    save_state(state)
    print(f"Done. {alerts_sent} alert(s) sent.")


if __name__ == "__main__":
    run()
