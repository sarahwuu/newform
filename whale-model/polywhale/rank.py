"""Rank open bets by total whale money.

Aggregates every trade that fits the whale criteria (>= min_cash notional,
entry below max_price) on markets that have not resolved, grouped by
(market, outcome), and ranks them by total notional wagered across ALL
whale wallets. The smart-money column shows how much of that total comes
from wallets with a statistically proven longshot record.
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import db
from .model import score_wallets


MAX_TRUE_PROB = 0.92   # never let alpha extrapolation claim near-certainty


@dataclass
class RankedBet:
    condition_id: str
    title: str
    outcome: str
    outcome_index: int
    event_slug: str
    total_notional: float = 0.0       # all whale dollars on this outcome
    smart_notional: float = 0.0       # portion from qualified ("smart") whales
    fresh_notional: float = 0.0       # portion from wallets with ~no history (burner pattern)
    burst_notional: float = 0.0       # portion that arrived within the last burst_hours
    n_trades: int = 0
    n_whales: int = 0
    weighted_entry: float = 0.0       # notional-weighted avg entry price
    latest_ts: int = 0
    end_ts: int = None                # scheduled market end (insider bets cluster near it)
    current_price: float = None       # live market price (None when offline)
    q_smart: float = None             # est. true probability implied by smart whales
    top_wallets: list = field(default_factory=list)  # (name, cash, is_smart, tags)

    def expected_value(self):
        """EV per $1 at the CURRENT price, from the smart whales' implied edge.

        q_smart is each proven whale's entry price scaled by their alpha
        (their demonstrated actual/expected win ratio), stake-weighted.
        Guard: if the market has collapsed well below the whales' entry, new
        information likely arrived after they bet — without this check a
        crashing price mechanically INFLATES EV, making the model love every
        bet where the whale is losing.
        """
        if self.q_smart is None or not self.current_price:
            return None
        if self.current_price < 0.6 * self.weighted_entry:
            return None    # adverse move too large: whales' entry view is stale
        return self.q_smart / self.current_price - 1


def rank_bets(con, cfg, window_days=None):
    """Return RankedBets sorted by total whale notional, largest first."""
    scores = score_wallets(
        db.resolved_buy_positions(con, cfg),
        prior_strength=cfg.prior_strength,
    )
    smart = {s.wallet: s for s in scores if s.qualifies(cfg)}

    days = cfg.signal_window_days if window_days is None else window_days
    now = int(time.time())
    since = now - days * 86400
    burst_cutoff = now - cfg.burst_hours * 3600
    grouped = defaultdict(list)
    for p in db.open_longshot_positions(con, cfg, since, burst_cutoff):
        grouped[(p["condition_id"], p["outcome"])].append(p)

    ranked = []
    for (condition_id, outcome), positions in grouped.items():
        notional = sum(p["cash"] for p in positions)
        event_slug = positions[0]["event_slug"] or ""
        outcome_index = positions[0]["outcome_index"]

        fresh_notional = 0.0
        wallets = []
        for p in positions:           # one row per wallet after aggregation
            tags = []
            if db.wallet_fill_count(con, p["wallet"]) <= cfg.fresh_wallet_max_fills:
                tags.append("fresh")     # burner-wallet pattern (see caveat in README)
                fresh_notional += p["cash"]
            if db.wallet_other_bets_in_event(con, p["wallet"], event_slug,
                                             condition_id, outcome_index, since):
                tags.append("hedged")    # also bought other outcomes of this event
            wallets.append((p["pseudonym"] or p["wallet"], p["cash"],
                            p["wallet"] in smart, ",".join(tags)))
        wallets.sort(key=lambda w: -w[1])

        # Stake-weighted true-probability estimate from proven whales only:
        # each smart wallet's entry price scaled by its demonstrated alpha.
        smart_pos = [p for p in positions if p["wallet"] in smart]
        q_smart = None
        if smart_pos:
            q_smart = sum(
                p["cash"] * min(MAX_TRUE_PROB, smart[p["wallet"]].alpha * p["price"])
                for p in smart_pos
            ) / sum(p["cash"] for p in smart_pos)

        ranked.append(RankedBet(
            condition_id=condition_id,
            title=positions[0]["title"] or condition_id,
            outcome=outcome or "?",
            outcome_index=outcome_index,
            event_slug=event_slug,
            total_notional=notional,
            smart_notional=sum(p["cash"] for p in smart_pos),
            q_smart=q_smart,
            fresh_notional=fresh_notional,
            burst_notional=sum(p["burst_cash"] for p in positions),
            n_trades=sum(p["fills"] for p in positions),
            n_whales=len(positions),
            weighted_entry=sum(p["cash"] * p["price"] for p in positions) / notional,
            latest_ts=max(p["latest_ts"] for p in positions),
            end_ts=positions[0]["end_ts"],
            top_wallets=wallets,
        ))
    ranked.sort(key=lambda b: -b.total_notional)
    return ranked


def attach_live_prices(bets, client):
    """Fetch current Gamma prices so whale entries can be compared to NOW.

    Mutates bets in place, setting current_price for any market Gamma returns.
    Callers should treat failures as non-fatal (offline -> prices stay None).
    """
    by_condition = defaultdict(list)
    for b in bets:
        by_condition[b.condition_id].append(b)
    markets = client.markets_by_condition_ids(by_condition.keys())
    for m in markets:
        prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
        for b in by_condition.get(m.get("conditionId"), []):
            if 0 <= b.outcome_index < len(prices):
                b.current_price = prices[b.outcome_index]
