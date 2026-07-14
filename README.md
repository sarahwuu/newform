# 🎯 Design Internship Watcher

An agent that watches for new **product design / UX / UI / UX research** internships
and 2027 new-grad roles the moment they drop, writes you an AI-tailored application
draft, and emails you — so you can apply within the hour, not within the week.

## How it works

Every ~15 minutes (free, on GitHub Actions):

1. **Scans sources**
   - SimplifyJobs GitHub lists (internships + new-grad) — updated within minutes of postings
   - Greenhouse / Lever / Ashby boards of ~40 companies directly — catches roles before they hit LinkedIn
   - LinkedIn public job search (last 24h, design queries)
2. **Filters** for design roles at intern/new-grad level (and filters *out* the
   hardware "ASIC Design Engineer" noise)
3. **Drafts** — for each new match, writes a markdown prep doc in `drafts/`:
   tailored pitch, "why this company", resume emphasis, short-answer bank
   (AI-tailored via Claude if `ANTHROPIC_API_KEY` is set; template otherwise)
4. **Alerts you by email** (or opens a GitHub Issue — which also emails you —
   until SMTP is configured)
5. Remembers what it already sent in `data/seen.json` so you're never pinged twice

You review the draft, paste, attach resume, hit submit. **The agent never
auto-submits** — you stay in control of every application.

## Setup (10 minutes)

### 1. Fill in your profile
Edit `profile.yaml` — portfolio URL, school, summary, highlights. The better
this is, the better the drafts.

### 2. Add your resume
Put `resume.pdf` in `materials/` (see the warning in `materials/README.md`
about public repos).

### 3. Add secrets (repo → Settings → Secrets and variables → Actions)

| Secret | Required? | What it is |
|---|---|---|
| `SMTP_USER` | for email alerts | your Gmail address (e.g. `sarahwu024@gmail.com`) |
| `SMTP_PASS` | for email alerts | a Gmail **App Password** — google.com → Security → 2-Step Verification → App passwords |
| `EMAIL_TO` | optional | where to send alerts (defaults to `SMTP_USER`) |
| `ANTHROPIC_API_KEY` | optional | enables AI-tailored drafts — get one at console.anthropic.com |

No secrets at all? It still works: alerts arrive as GitHub Issues (GitHub
emails you those), and drafts use the built-in template.

### 4. Turn it on
GitHub Actions is on by default once this is merged to the default branch.
Trigger the first scan manually: **Actions → "Watch for new design roles" → Run workflow**.
The first run alerts only the 25 newest matches and quietly memorizes the backlog.

## Tuning

Everything lives in `config.yaml`:
- **Add/remove companies** under `sources.greenhouse/lever/ashby` — the slug is in the
  careers page URL (`job-boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`,
  `jobs.ashbyhq.com/<slug>`). Wrong slugs are skipped harmlessly.
- **Keywords** — add or remove role keywords / exclusions
- **`level.require: false`** — also catch unmarked "Product Designer" roles (more noise)
- **LinkedIn queries** — edit `sources.linkedin.queries`

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
- GitHub Actions cron can lag 5–15 min under load. If you want minute-level
  polling, run `python -m agent.main` on a cron on any always-on machine.
