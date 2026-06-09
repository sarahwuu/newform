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
    top_wallets: list = field(default_factory=list)  # (name, cash, is_smart, tags)


def rank_bets(con, cfg, window_days=None):
    """Return RankedBets sorted by total whale notional, largest first."""
    scores = score_wallets(
        db.resolved_longshot_buys(con, cfg.max_price),
        prior_strength=cfg.prior_strength,
    )
    smart = {s.wallet for s in scores if s.qualifies(cfg)}

    days = cfg.signal_window_days if window_days is None else window_days
    since = int(time.time()) - days * 86400
    grouped = defaultdict(list)
    for t in db.open_longshot_buys(con, cfg.max_price, since):
        grouped[(t["condition_id"], t["outcome"])].append(t)

    now = int(time.time())
    burst_cutoff = now - cfg.burst_hours * 3600
    ranked = []
    for (condition_id, outcome), trades in grouped.items():
        notional = sum(t["cash"] for t in trades)
        event_slug = trades[0]["event_slug"] or ""
        outcome_index = trades[0]["outcome_index"]
        per_wallet = defaultdict(float)
        for t in trades:
            per_wallet[(t["pseudonym"] or t["wallet"], t["wallet"])] += t["cash"]

        fresh_notional = 0.0
        wallets = []
        for (name, wallet), cash in per_wallet.items():
            tags = []
            if db.wallet_fill_count(con, wallet) <= cfg.fresh_wallet_max_fills:
                tags.append("fresh")     # burner-wallet pattern (see caveat in README)
                fresh_notional += cash
            if db.wallet_other_bets_in_event(con, wallet, event_slug,
                                             condition_id, outcome_index, since):
                tags.append("hedged")    # also bought other outcomes of this event
            wallets.append((name, cash, wallet in smart, ",".join(tags)))
        wallets.sort(key=lambda w: -w[1])

        ranked.append(RankedBet(
            condition_id=condition_id,
            title=trades[0]["title"] or condition_id,
            outcome=outcome or "?",
            outcome_index=outcome_index,
            event_slug=event_slug,
            total_notional=notional,
            smart_notional=sum(t["cash"] for t in trades if t["wallet"] in smart),
            fresh_notional=fresh_notional,
            burst_notional=sum(t["cash"] for t in trades if t["ts"] >= burst_cutoff),
            n_trades=len(trades),
            n_whales=len(per_wallet),
            weighted_entry=sum(t["cash"] * t["price"] for t in trades) / notional,
            latest_ts=max(t["ts"] for t in trades),
            end_ts=trades[0]["end_ts"],
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
