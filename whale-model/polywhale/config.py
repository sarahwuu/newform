"""Tunable thresholds for the whale model."""

from dataclasses import dataclass


@dataclass
class Config:
    # Whale definition — applied at the POSITION level (fills aggregated per
    # wallet+market+outcome), because real whales clip orders: a $40k position
    # built from eight $5k fills must count, a lone $10k punt must not gain
    # rank just for arriving in one print.
    ingest_min_cash: float = 2_000.0       # fill floor stored to the DB
    min_position_cash: float = 10_000.0    # whale = total position notional >= this
    min_price: float = 0.02      # below ~2c: lottery dust, huge spreads, arb legs
    max_price: float = 0.20      # longshot ceiling

    # Track-record scoring uses ALL resolved buys (any price band), because
    # whales place too few sub-20c bets to build a sample from those alone —
    # real data: ~182 resolved longshot positions across 1,289 wallets. Every
    # bet at price p tests the wallet against probability p, so mid-range
    # bets are equally valid evidence. The longshot band above applies to
    # SIGNALS (which open bets get surfaced), not to evidence.
    scoring_min_cash: float = 2_000.0   # position floor for track-record evidence
    scoring_min_price: float = 0.01     # ignore dust prices when scoring
    scoring_max_price: float = 0.95     # ignore near-certainties when scoring

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
    burner_max_markets: int = 3       # hunt: a concentrated insider burner touches
                                      # <= this many markets; sprayers/hedgers exceed it

    # Signal generation
    signal_window_days: int = 14  # only treat recent whale entries as live signals

    db_path: str = "polywhale.db"
