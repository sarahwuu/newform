"""Tunable thresholds for the whale model."""

from dataclasses import dataclass


@dataclass
class Config:
    # Whale definition
    min_cash: float = 10_000.0   # minimum USDC notional per trade
    max_price: float = 0.20      # only longshot entries below this price

    # Wallet qualification ("smart whale")
    min_resolved: int = 5        # resolved longshot bets needed before we trust a wallet
    min_z: float = 1.0           # significance of outperformance vs. market-efficient null
    min_alpha: float = 1.15      # shrunken actual/expected win ratio must beat this
    prior_strength: float = 3.0  # pseudo-bets at alpha=1 used to shrink small samples

    # Signal generation
    signal_window_days: int = 14  # only treat recent whale entries as live signals

    db_path: str = "polywhale.db"
