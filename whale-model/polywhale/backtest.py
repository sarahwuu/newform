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
    predicted_ev_sum: float = 0.0   # sum of model EV at each copy decision
    by_wallet: dict = field(default_factory=dict)

    @property
    def roi(self):
        return self.profit / self.staked if self.staked else 0.0

    @property
    def predicted_ev(self):
        """Average EV the model claimed at decision time. If this tracks the
        realized ROI, the alpha-based EV estimates are honest."""
        return self.predicted_ev_sum / self.copied if self.copied else 0.0


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

    def alpha(self, cfg):
        return (self.wins + cfg.prior_strength) / (self.expected + cfg.prior_strength)

    def qualifies(self, cfg):
        if self.n < cfg.min_resolved or self.variance <= 0:
            return False
        z = (self.wins - self.expected) / math.sqrt(self.variance)
        return z >= cfg.min_z and self.alpha(cfg) >= cfg.min_alpha


def walk_forward(resolved_positions, cfg, stake=100.0, copy_all_prices=False):
    """resolved_positions: ALL resolved BUY positions (any price), ts-sorted.

    Track records build from every position. What gets COPIED is the strategy
    under evaluation: by default only signal-band positions (longshot price
    band, whale-size notional); with copy_all_prices, every whale-size
    position by a qualified wallet — "follow proven whales wherever they
    bet", which is where most of their opportunity surface actually is.
    """
    wallets = {}
    result = BacktestResult()

    for t in resolved_positions:
        w = wallets.setdefault(t["wallet"], _Running())
        w.settle_until(t["ts"])

        price, won = float(t["price"]), bool(t["won"])
        copyable = float(t["cash"]) >= cfg.min_position_cash and (
            copy_all_prices or cfg.min_price <= price < cfg.max_price)
        if copyable and w.qualifies(cfg):
            pnl = stake * (1 / price - 1) if won else -stake
            result.copied += 1
            result.wins += won
            result.staked += stake
            result.profit += pnl
            result.expected_wins += price
            # Under the multiplicative skill model, copying at the whale's
            # entry price has EV = alpha - 1 per $1 regardless of the price.
            result.predicted_ev_sum += w.alpha(cfg) - 1
            name = t["pseudonym"] or t["wallet"]
            agg = result.by_wallet.setdefault(name, {"copied": 0, "profit": 0.0})
            agg["copied"] += 1
            agg["profit"] += pnl

        # The bet only becomes knowledge once its market resolves.
        end_ts = t["end_ts"] or t["ts"]
        w.pending.append((max(end_ts, t["ts"] + 1), price, won))

    return result
