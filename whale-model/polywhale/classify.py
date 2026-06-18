"""Classify a Polymarket market into a category from its title / event slug.

Polymarket's category field comes back empty over the API, so we infer from
the slug/title. Matching is conservative: short codes match only as whole
slug segments (so "ucl" never matches inside "nuclear"), longer phrases match
as substrings.

`category()` returns a fine-grained bucket; `classify_market()` keeps the
older sports/other split that hunt and the ledger already use.
"""

import re

# --- sports -----------------------------------------------------------------
_SPORT_SEGMENTS = {
    "fifwc", "worldcup", "nba", "wnba", "nfl", "mlb", "nhl", "ncaa", "ufc",
    "epl", "laliga", "bundesliga", "ucl", "europa", "euros", "copa",
    "concacaf", "f1", "pga", "atp", "wta", "tennis", "cricket", "ipl",
    "rugby", "superbowl", "playoffs", "finals", "champion", "champions",
    "vs", "v",
}
_SPORT_PHRASES = (
    "world-cup", "premier-league", "la-liga", "serie-a", "ligue-1",
    "champions-league", "euro-2026", "grand-prix", "super-bowl", "-vs-",
)
_MATCHDAY = re.compile(r"\bwin on \d{4}-\d{2}-\d{2}\b", re.IGNORECASE)

# --- weather (the category where skill genuinely persists) ------------------
_WEATHER_SEG = {
    "temperature", "temp", "weather", "rain", "rainfall", "snow", "snowfall",
    "hurricane", "heat", "degrees", "celsius", "fahrenheit", "storm",
    "tornado", "precipitation",
}
_WEATHER_PHRASE = ("high-temp", "low-temp", "highest-temperature",
                   "will-it-rain", "inches-of-snow", "named-storm")

# --- crypto -----------------------------------------------------------------
_CRYPTO_SEG = {
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "xrp",
    "dogecoin", "doge", "cardano", "ada", "litecoin",
}
_CRYPTO_PHRASE = ("price-of-bitcoin", "all-time-high", "hit-100k", "hit-150k")

# --- economy / finance ------------------------------------------------------
_ECON_SEG = {
    "fed", "fomc", "federal", "cpi", "gdp", "inflation", "recession",
    "unemployment", "nasdaq", "stocks", "earnings", "ipo", "nvidia",
}
_ECON_PHRASE = ("interest-rate", "rate-cut", "rate-hike", "jobs-report",
                "market-cap", "largest-company", "stock-market", "s-and-p")

# --- politics ---------------------------------------------------------------
_POLITICS_SEG = {
    "election", "president", "presidential", "senate", "congress", "nominee",
    "primary", "parliament", "governor", "impeach", "impeachment", "cabinet",
    "vote", "referendum", "minister", "mayor", "approval", "poll", "ballot",
}
_POLITICS_PHRASE = ("prime-minister", "supreme-court", "white-house",
                    "balance-of-power", "presidential-election")


def _hit(segs, slug, seg_set, phrases):
    return bool(segs & seg_set) or any(p in slug for p in phrases)


def category(title, event_slug):
    """Return one of: weather, crypto, economy, politics, sports, other."""
    slug = (event_slug or "").lower()
    text = (title or "").lower()
    segs = set(re.split(r"[^a-z0-9]+", slug))
    if _hit(segs, slug, _WEATHER_SEG, _WEATHER_PHRASE):
        return "weather"
    if _hit(segs, slug, _CRYPTO_SEG, _CRYPTO_PHRASE):
        return "crypto"
    if _hit(segs, slug, _ECON_SEG, _ECON_PHRASE):
        return "economy"
    if _hit(segs, slug, _POLITICS_SEG, _POLITICS_PHRASE):
        return "politics"
    if (_MATCHDAY.search(text) or (segs & _SPORT_SEGMENTS)
            or any(p in slug for p in _SPORT_PHRASES)):
        return "sports"
    return "other"


def classify_market(title, event_slug):
    """Coarse split used by hunt/ledger: 'sports' or 'other'."""
    return "sports" if category(title, event_slug) == "sports" else "other"
