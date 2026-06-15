"""Classify a market as sports vs. other from its title / event slug.

Why this matters: every live signature hit so far has been a sports match.
Sports is the category where "insider" usually means match-fixing or a
late team-news leak — legally radioactive, often voided by the exchange,
and resolving within hours so you can't act anyway. The signals worth real
money live in NEWS-driven markets (politics, courts, regulation, awards),
which resolve over days and reflect information, not manipulation.

Polymarket's category field comes back empty over the API, so we infer
from the slug/title. The heuristic is deliberately conservative: it only
calls something "sports" on a clear signal, leaving genuinely ambiguous
markets as "other".
"""

import re

# Single-segment league/sport codes — matched as WHOLE slug segments only,
# never as substrings (so "ucl" never matches inside "nuclear").
_SPORT_SEGMENTS = {
    "fifwc", "worldcup", "nba", "wnba", "nfl", "mlb", "nhl", "ncaa", "ufc",
    "epl", "laliga", "bundesliga", "ucl", "europa", "euros", "copa",
    "concacaf", "f1", "pga", "atp", "wta", "tennis", "cricket", "ipl",
    "rugby", "superbowl", "playoffs", "finals", "champion", "champions",
    "vs", "v",
}

# Hyphenated phrases — safe to match as substrings because the hyphens keep
# them from matching inside a single word.
_SPORT_PHRASES = (
    "world-cup", "premier-league", "la-liga", "serie-a", "ligue-1",
    "champions-league", "euro-2026", "grand-prix", "super-bowl", "-vs-",
)

# "Will <team> win on 2026-06-15" — the daily single-match pattern.
_MATCHDAY = re.compile(r"\bwin on \d{4}-\d{2}-\d{2}\b", re.IGNORECASE)


def classify_market(title, event_slug):
    """Return 'sports' or 'other'."""
    slug = (event_slug or "").lower()
    text = (title or "").lower()
    if _MATCHDAY.search(text):
        return "sports"
    if any(p in slug for p in _SPORT_PHRASES):
        return "sports"
    segments = set(re.split(r"[^a-z0-9]+", slug))
    if segments & _SPORT_SEGMENTS:
        return "sports"
    return "other"
