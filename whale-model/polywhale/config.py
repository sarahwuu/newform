"""Tunable thresholds for the whale model."""

from dataclasses import dataclass


@dataclass
class Config:
    # Whale definition
    min_cash: float = 10_000.0   # minimum USDC notional per trade
    max_price: float = 0.20      # only longshot entries below this price

    # Wallet qualification ("smart whale"). Thresholds apply to POSITIONS
    # (fills aggregated per market+outcome), not raw fills. min_z is set high
    # deliberately: scanning thousands of wallets is a multiple-comparisons
    # problem — at z>=1 about 1 in 6 zero-edge gamblers qualifies by luck,
    # at z>=2 about 1 in 44.
    min_resolved: int = 8        # resolved longshot positions before we trust a wallet
    min_z: float = 2.0           # significance of outperformance vs. market-efficient null
    min_alpha: float = 1.15      # shrunken actual/expected win ratio must beat this
    prior_strength: float = 3.0  # pseudo-bets at alpha=1 used to shrink small samples

    # Insider-pattern heuristics (display flags, not filters)
    fresh_wallet_max_fills: int = 3   # wallet with <= this many fills in DB = "fresh"
    burst_hours: int = 24             # window for "money arriving suddenly" share

    # Signal generation
    signal_window_days: int = 14  # only treat recent whale entries as live signals

    db_path: str = "polywhale.db"
