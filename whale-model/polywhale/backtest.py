"""Walk-forward copy-trade backtest.

For every whale longshot bet (in time order) we ask: using only bets of theirs
that had RESOLVED before this moment, did the wallet already qualify as smart?
If yes, we copy the bet with a fixed stake. No information from the future
leaks into the decision: resolution timestamps gate what the strategy knows.

Market end time is used as the resolution timestamp (Gamma does not expose the
exact UMA settlement time through this dataset); that is a close, slightly
conservative proxy.
"""

import math
from dataclasses import dataclass, field


@dataclass
class BacktestResult:
    copied: int = 0
    wins: int = 0
    staked: float = 0.0
    profit: float = 0.0
    expected_wins: float = 0.0
    by_wallet: dict = field(default_factory=dict)

    @property
    def roi(self):
        return self.profit / self.staked if self.staked else 0.0


class _Running:
    """Per-wallet stats over bets whose markets have already resolved."""

    __slots__ = ("pending", "i", "n", "wins", "expected", "variance")

    def __init__(self):
        self.pending = []  # (resolve_ts, price, won), appended in trade order
        self.i = 0
        self.n = 0
        self.wins = 0
        self.expected = 0.0
        self.variance = 0.0

    def settle_until(self, now_ts):
        self.pending.sort(key=lambda x: x[0])
        while self.i < len(self.pending) and self.pending[self.i][0] < now_ts:
            _, p, won = self.pending[self.i]
            self.n += 1
            self.wins += won
            self.expected += p
            self.variance += p * (1 - p)
            self.i += 1

    def qualifies(self, cfg):
        if self.n < cfg.min_resolved or self.variance <= 0:
            return False
        alpha = (self.wins + cfg.prior_strength) / (self.expected + cfg.prior_strength)
        z = (self.wins - self.expected) / math.sqrt(self.variance)
        return z >= cfg.min_z and alpha >= cfg.min_alpha


def walk_forward(resolved_trades, cfg, stake=100.0):
    """resolved_trades: rows with wallet, price, cash, ts, end_ts, won — ts-sorted."""
    wallets = {}
    result = BacktestResult()

    for t in resolved_trades:
        w = wallets.setdefault(t["wallet"], _Running())
        w.settle_until(t["ts"])

        price, won = float(t["price"]), bool(t["won"])
        if w.qualifies(cfg):
            pnl = stake * (1 / price - 1) if won else -stake
            result.copied += 1
            result.wins += won
            result.staked += stake
            result.profit += pnl
            result.expected_wins += price
            name = t["pseudonym"] or t["wallet"]
            agg = result.by_wallet.setdefault(name, {"copied": 0, "profit": 0.0})
            agg["copied"] += 1
            agg["profit"] += pnl

        # The bet only becomes knowledge once its market resolves.
        end_ts = t["end_ts"] or t["ts"]
        w.pending.append((max(end_ts, t["ts"] + 1), price, won))

    return result
