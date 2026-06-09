"""Live signals: open markets where proven whales hold fresh longshot bets."""

import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import db
from .model import score_wallets


@dataclass
class Signal:
    condition_id: str
    title: str
    outcome: str
    event_slug: str
    smart_notional: float = 0.0
    weighted_entry: float = 0.0       # notional-weighted avg entry price
    latest_ts: int = 0
    wallets: list = field(default_factory=list)  # (pseudonym/wallet, z, cash)


def generate(con, cfg):
    """Return Signals sorted by smart-money notional, largest first."""
    scores = score_wallets(
        db.resolved_longshot_buys(con, cfg.max_price),
        prior_strength=cfg.prior_strength,
    )
    smart = {s.wallet: s for s in scores if s.qualifies(cfg)}
    if not smart:
        return []

    since = int(time.time()) - cfg.signal_window_days * 86400
    grouped = defaultdict(list)
    for t in db.open_longshot_buys(con, cfg.max_price, since):
        if t["wallet"] in smart:
            grouped[(t["condition_id"], t["outcome"])].append(t)

    signals = []
    for (condition_id, outcome), trades in grouped.items():
        notional = sum(t["cash"] for t in trades)
        sig = Signal(
            condition_id=condition_id,
            title=trades[0]["title"] or condition_id,
            outcome=outcome or "?",
            event_slug=trades[0]["event_slug"] or "",
            smart_notional=notional,
            weighted_entry=sum(t["cash"] * t["price"] for t in trades) / notional,
            latest_ts=max(t["ts"] for t in trades),
            wallets=sorted(
                {(t["pseudonym"] or t["wallet"],
                  round(smart[t["wallet"]].z, 2),
                  t["cash"]) for t in trades},
                key=lambda w: -w[2],
            ),
        )
        signals.append(sig)
    signals.sort(key=lambda s: -s.smart_notional)
    return signals
