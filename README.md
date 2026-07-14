# 🎯 Design Internship Watcher

An agent that watches for new **product design / UX / UI / UX research** internships
and 2027 new-grad roles and emails you the moment they drop — so you can apply
within the hour, not within the week.

## How it works

Every hour (free, on GitHub Actions):

1. **Scans sources**
   - SimplifyJobs GitHub lists (internships + new-grad) — updated within minutes of postings
   - Greenhouse / Lever / Ashby boards of ~40 companies directly — catches roles before they hit LinkedIn
   - LinkedIn public job search (last 24h, design queries)
2. **Filters** for design roles at intern/new-grad level (and filters *out* the
   hardware "ASIC Design Engineer" noise)
3. **Emails you** the new matches (or opens a GitHub Issue — which also emails
   you — until SMTP is configured)
4. Remembers what it already sent in `data/seen.json` so you're never pinged twice

## Setup

Add secrets at repo → Settings → Secrets and variables → Actions:

| Secret | Required? | What it is |
|---|---|---|
| `SMTP_USER` | for email alerts | your Gmail address |
| `SMTP_PASS` | for email alerts | a Gmail **App Password** (no spaces) — google.com → Security → 2-Step Verification → App passwords |
| `EMAIL_TO` | optional | where to send alerts (defaults to `SMTP_USER`) |

No secrets? It still works: alerts arrive as GitHub Issues labeled `job-alert`,
and GitHub emails you those.

## Tuning

Everything lives in `config.yaml`:
- **Add/remove companies** under `sources.greenhouse/lever/ashby` — the slug is in the
  careers page URL (`job-boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`,
  `jobs.ashbyhq.com/<slug>`). Wrong slugs are skipped harmlessly.
- **Keywords** — add or remove role keywords / exclusions
- **`level.require: false`** — also catch unmarked "Product Designer" roles (more noise)
- **LinkedIn queries** — edit `sources.linkedin.queries`
- **Schedule** — the cron in `.github/workflows/watch.yml` (hourly keeps a private
  repo well inside GitHub's 2,000 free Actions minutes/month)

## Run locally

```bash
pip install -r requirements.txt
python -m agent.main
```

## Known limits (honest edition)

- **Handshake** can't be watched — it's behind your school's SSO with no public API.
- **Indeed** aggressively blocks bots; not included.
- **LinkedIn** guest search works but gets rate-limited sometimes; failures are
  logged and skipped, never fatal — the other sources keep working.
- GitHub Actions cron can lag 5–15 min. Scheduled workflows pause if the repo
  sees no activity for 60 days (the agent's own commits normally keep it alive).
