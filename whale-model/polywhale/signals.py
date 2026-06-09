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
        db.resolved_longshot_buys(con, cfg),
        prior_strength=cfg.prior_strength,
    )
    smart = {s.wallet: s for s in scores if s.qualifies(cfg)}
    if not smart:
        return []

    now = int(time.time())
    since = now - cfg.signal_window_days * 86400
    burst_cutoff = now - cfg.burst_hours * 3600
    grouped = defaultdict(list)
    for p in db.open_longshot_positions(con, cfg, since, burst_cutoff):
        if p["wallet"] in smart:
            grouped[(p["condition_id"], p["outcome"])].append(p)

    signals = []
    for (condition_id, outcome), positions in grouped.items():
        notional = sum(p["cash"] for p in positions)
        sig = Signal(
            condition_id=condition_id,
            title=positions[0]["title"] or condition_id,
            outcome=outcome or "?",
            event_slug=positions[0]["event_slug"] or "",
            smart_notional=notional,
            weighted_entry=sum(p["cash"] * p["price"] for p in positions) / notional,
            latest_ts=max(p["latest_ts"] for p in positions),
            wallets=sorted(
                ((p["pseudonym"] or p["wallet"],
                  round(smart[p["wallet"]].z, 2),
                  p["cash"]) for p in positions),
                key=lambda w: -w[2],
            ),
        )
        signals.append(sig)
    signals.sort(key=lambda s: -s.smart_notional)
    return signals
