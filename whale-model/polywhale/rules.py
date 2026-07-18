"""Rules-gap scanner: find markets where the resolution criteria likely
diverge from the naive reading of the title.

This is the one edge class the whale investigation left standing: it does not
copy anyone. Casual bettors price the *headline* ("will Argentina win?",
"is Hormuz back to normal?"); the market actually resolves on the *rules text*
(the 90-minute result; a lagging 7-day moving average from one named source).
The gap between those two readings is a legal, structural mispricing — and
reading the rules is an edge anyone can have.

Each check is a heuristic over the market's description. Findings are leads
for HUMAN judgment, not signals: the scanner tells you where to read the fine
print, never which side to bet.
"""

import json
import re

# (name, pattern, why-casuals-misread-this) — patterns run over the market
# description, case-insensitively.
_CHECKS = [
    ("regulation-time",
     r"regulation time|90 minutes|ninety minutes|end of regulation"
     r"|extra time|penalty shootout|penalt(?:y|ies)(?: kicks)?",
     "Match markets often resolve on the 90-minute result: a draw counts as "
     "NO even if the favorite advances on extra time/penalties. Casuals "
     "price 'wins the tie'."),
    ("data-threshold",
     r"moving average|rolling average|\d+-day average|average of|averaged"
     r"|at or above \d|above \d+|below \d+|threshold of",
     "Resolves on a numeric threshold or an averaged data series. Averages "
     "lag reality — 'it happened' and 'the number crossed in time' are "
     "different events (see Strait of Hormuz, June 2026)."),
    ("named-source",
     r"as reported by|according to|reported by|data (?:published|provided) by"
     r"|per the [A-Z]|IMF|Lloyd'?s|Bureau of|official (?:data|figures|statistics)",
     "Resolution depends on ONE named source's figure, which can lag events "
     "or differ from common knowledge."),
    ("official-definition",
     r"officially|formally announce|publicly announce|signed into law"
     r"|sworn in|takes office|certif(?:y|ied|ication)|ratif(?:y|ied|ication)",
     "Hinges on a formal/official act, not the event itself — timing and "
     "technical definitions bite."),
    ("compound-conditions",
     r"both of the|all of the following|must also|and must|in addition, the",
     "Multiple conditions must ALL hold; casuals price only the headline "
     "condition."),
]
_COMPILED = [(name, re.compile(rx, re.IGNORECASE), why)
             for name, rx, why in _CHECKS]

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentence_around(text, match, max_len=220):
    """Return the sentence of `text` containing the regex match, truncated."""
    for sentence in _SENTENCE_SPLIT.split(text):
        if match.group(0).lower() in sentence.lower():
            s = " ".join(sentence.split())
            return s[:max_len] + ("…" if len(s) > max_len else "")
    return match.group(0)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _yes_price(m):
    try:
        return float(json.loads(m.get("outcomePrices") or "[]")[0])
    except (ValueError, IndexError, TypeError):
        return None


def scan_rules_gaps(markets):
    """Scan Gamma market objects; return findings sorted by volume, largest
    first. One finding per market, listing every gap class its rules trip."""
    findings = []
    for m in markets:
        desc = m.get("description") or ""
        if not desc:
            continue
        gaps = []
        snippet = None
        for name, rx, why in _COMPILED:
            match = rx.search(desc)
            if match:
                gaps.append((name, why))
                if snippet is None:
                    snippet = _sentence_around(desc, match)
        if gaps:
            findings.append({
                "question": m.get("question") or "",
                "slug": m.get("slug") or "",
                "gaps": gaps,
                "snippet": snippet,
                "volume": _num(m.get("volumeNum") or m.get("volume")),
                "yes_price": _yes_price(m),
            })
    findings.sort(key=lambda f: -f["volume"])
    return findings
