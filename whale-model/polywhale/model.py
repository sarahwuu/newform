"""Wallet skill model: do a whale's longshot bets beat their implied odds?

Null hypothesis: markets are efficient, so a bet entered at price p wins with
probability p. For each wallet we compare actual wins against the sum of entry
prices (the expected win count under the null):

  alpha = (wins + c) / (expected_wins + c)     shrunken outperformance ratio
  z     = (wins - expected) / sqrt(sum p(1-p)) significance vs. the null

alpha > 1 means the wallet's longshots land more often than the market priced
them; the prior strength c pulls small samples back toward 1 so a whale who
went 2-for-2 on 15c bets doesn't outrank one who is 30-for-100. The z-score
guards against crowning whales who are merely lucky.
"""

import math
from dataclasses import dataclass


@dataclass
class WalletScore:
    wallet: str
    pseudonym: str
    n: int                 # resolved longshot bets
    wins: int
    expected_wins: float   # sum of entry prices
    staked: float          # total USDC put at risk
    profit: float          # realized P&L (binary payoff: cash/price if win)
    roi: float
    alpha: float
    z: float

    def qualifies(self, cfg):
        return (self.n >= cfg.min_resolved
                and self.z >= cfg.min_z
                and self.alpha >= cfg.min_alpha)


def score_wallets(resolved_trades, prior_strength=3.0):
    """Aggregate resolved (wallet, pseudonym, price, cash, won) rows per wallet.

    Accepts any iterable of mappings with those keys (sqlite3.Row included).
    Returns WalletScores sorted by z descending.
    """
    stats = {}
    for t in resolved_trades:
        s = stats.setdefault(t["wallet"], {
            "pseudonym": t["pseudonym"] or "",
            "n": 0, "wins": 0, "expected": 0.0, "variance": 0.0,
            "staked": 0.0, "payout": 0.0,
        })
        p, cash, won = float(t["price"]), float(t["cash"]), bool(t["won"])
        s["n"] += 1
        s["wins"] += won
        s["expected"] += p
        s["variance"] += p * (1 - p)
        s["staked"] += cash
        if won:
            s["payout"] += cash / p

    scores = []
    for wallet, s in stats.items():
        profit = s["payout"] - s["staked"]
        alpha = (s["wins"] + prior_strength) / (s["expected"] + prior_strength)
        z = ((s["wins"] - s["expected"]) / math.sqrt(s["variance"])
             if s["variance"] > 0 else 0.0)
        scores.append(WalletScore(
            wallet=wallet,
            pseudonym=s["pseudonym"],
            n=s["n"],
            wins=s["wins"],
            expected_wins=s["expected"],
            staked=s["staked"],
            profit=profit,
            roi=profit / s["staked"] if s["staked"] else 0.0,
            alpha=alpha,
            z=z,
        ))
    scores.sort(key=lambda x: x.z, reverse=True)
    return scores
