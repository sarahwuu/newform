"""Offline smoke test: synthetic whales with known skill levels.

Builds a population of wallets betting $10k+ on 5-19c longshots:
  - "sharp" wallets whose true win probability is 2x the entry price
  - "noise" wallets who win exactly at the implied rate (no edge)

Verifies that scoring ranks sharps on top, that qualification rejects noise,
that the walk-forward backtest is profitable on sharps without lookahead, and
that the DB layer round-trips Data API / Gamma payload shapes.

Run:  python tests/smoke_test.py
"""

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from polywhale import db
from polywhale.backtest import walk_forward
from polywhale.config import Config
from polywhale.model import score_wallets
from polywhale.signals import generate

rng = random.Random(42)
CFG = Config()


def synth_trades(wallet, n, skill, start_ts=1_700_000_000):
    rows = []
    for i in range(n):
        price = rng.uniform(0.05, 0.19)
        won = rng.random() < min(1.0, price * skill)
        ts = start_ts + i * 86_400
        rows.append({
            "wallet": wallet, "pseudonym": wallet, "price": price,
            "cash": rng.uniform(10_000, 60_000), "ts": ts,
            "end_ts": ts + 3 * 86_400, "won": won, "title": f"market-{i}",
        })
    return rows


def test_scoring_separates_skill():
    trades = []
    for w in range(5):
        trades += synth_trades(f"sharp-{w}", 60, skill=2.0)
    for w in range(20):
        trades += synth_trades(f"noise-{w}", 60, skill=1.0)
    rng.shuffle(trades)

    scores = score_wallets(trades, CFG.prior_strength)
    top5 = {s.wallet for s in scores[:5]}
    assert top5 == {f"sharp-{w}" for w in range(5)}, f"top5 was {top5}"

    qualified = {s.wallet for s in scores if s.qualifies(CFG)}
    sharps_found = sum(1 for w in qualified if w.startswith("sharp"))
    noise_found = sum(1 for w in qualified if w.startswith("noise"))
    assert sharps_found == 5, f"only {sharps_found}/5 sharps qualified"
    assert noise_found <= 4, f"{noise_found}/20 zero-edge wallets qualified"
    print(f"  scoring: 5/5 sharps on top, {noise_found}/20 noise false positives")


def test_backtest_walk_forward():
    trades = []
    for w in range(5):
        trades += synth_trades(f"sharp-{w}", 80, skill=2.0)
    for w in range(20):
        trades += synth_trades(f"noise-{w}", 80, skill=1.0)
    trades.sort(key=lambda t: t["ts"])

    res = walk_forward(trades, CFG, stake=100.0)
    assert res.copied > 50, f"too few copies: {res.copied}"
    assert res.roi > 0.3, f"copying sharps should be clearly +EV, got {res.roi:.1%}"

    # Sanity: copying ONLY zero-edge wallets must not look profitable.
    noise_only = [t for t in trades if t["wallet"].startswith("noise")]
    res_noise = walk_forward(noise_only, CFG, stake=100.0)
    assert res_noise.roi < res.roi, "noise outperformed sharps?!"
    print(f"  backtest: copied {res.copied} bets, ROI {res.roi:.1%} "
          f"(noise-only control: {res_noise.roi:.1%} on {res_noise.copied} copies)")


def test_db_roundtrip_and_signals():
    raw_trade = {  # Data API /trades shape
        "transactionHash": "0xabc", "proxyWallet": "0xWALLET",
        "conditionId": "0xcond1", "outcomeIndex": 1, "outcome": "Yes",
        "side": "BUY", "price": 0.12, "size": 100_000,
        "timestamp": 1_900_000_000, "title": "Will X happen?",
        "eventSlug": "will-x-happen", "pseudonym": "Test-Whale",
    }
    gamma_market = {  # Gamma API /markets shape (resolved, index 1 won)
        "conditionId": "0xcond0", "question": "Old market", "category": "Politics",
        "closed": True, "outcomePrices": '["0", "1"]',
        "endDate": "2026-01-01T00:00:00Z",
    }
    with tempfile.TemporaryDirectory() as tmp:
        con = db.connect(os.path.join(tmp, "t.db"))
        # History: 8 resolved wins at 12c for the same wallet -> qualifies.
        history = []
        for i in range(8):
            h = dict(raw_trade, transactionHash=f"0xh{i}", conditionId="0xcond0",
                     timestamp=1_800_000_000 + i)
            history.append(h)
        added = db.upsert_trades(con, history + [raw_trade, raw_trade])
        assert added == 9, f"dedupe failed: {added}"
        db.upsert_market(con, gamma_market)

        resolved = db.resolved_longshot_buys(con, CFG.max_price)
        assert len(resolved) == 8 and all(r["won"] for r in resolved)

        cfg = Config(signal_window_days=10_000_000)  # huge window for fixed ts
        sigs = generate(con, cfg)
        assert len(sigs) == 1 and sigs[0].outcome == "Yes"
        assert sigs[0].smart_notional == 0.12 * 100_000
        print(f"  db+signals: dedupe ok, resolution join ok, "
              f"1 signal @ ${sigs[0].smart_notional:,.0f} smart notional")


if __name__ == "__main__":
    for fn in (test_scoring_separates_skill, test_backtest_walk_forward,
               test_db_roundtrip_and_signals):
        print(f"{fn.__name__} ...")
        fn()
    print("\nall smoke tests passed")
