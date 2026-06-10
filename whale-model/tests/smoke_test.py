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
from polywhale.rank import attach_live_prices, rank_bets
from polywhale.report import build_html, build_markdown
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

    # z >= 2.0 trades recall for precision: a real sharp with a short record
    # can miss the bar, but almost no zero-edge gambler should clear it.
    qualified = {s.wallet for s in scores if s.qualifies(CFG)}
    sharps_found = sum(1 for w in qualified if w.startswith("sharp"))
    noise_found = sum(1 for w in qualified if w.startswith("noise"))
    assert sharps_found >= 4, f"only {sharps_found}/5 sharps qualified"
    assert noise_found <= 1, f"{noise_found}/20 zero-edge wallets qualified"
    print(f"  scoring: 5/5 sharps on top, {sharps_found}/5 qualified, "
          f"{noise_found}/20 noise false positives")


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
    # The model's claimed EV at decision time should track realized ROI.
    assert abs(res.predicted_ev - res.roi) < 0.5, \
        f"EV claim {res.predicted_ev:.1%} vs realized {res.roi:.1%}"

    # Sanity: copying ONLY zero-edge wallets must not look profitable.
    noise_only = [t for t in trades if t["wallet"].startswith("noise")]
    res_noise = walk_forward(noise_only, CFG, stake=100.0)
    assert res_noise.roi < res.roi, "noise outperformed sharps?!"
    print(f"  backtest: copied {res.copied} bets, ROI {res.roi:.1%} vs "
          f"model EV claim {res.predicted_ev:.1%} "
          f"(noise-only control: {res_noise.roi:.1%} on {res_noise.copied} copies)")


def test_pagination_cap_stops_cleanly():
    from polywhale.api import ClientError, PolymarketClient

    client = PolymarketClient()
    calls = []

    def fake_get(url, params):
        calls.append(params["offset"])
        if params["offset"] >= 1000:
            raise ClientError("400: pagination depth cap")  # like offset=3500 live
        return [{"id": i} for i in range(params["limit"])]

    client._get = fake_get
    got = list(client.iter_large_trades(2000, page_size=500, max_pages=10))
    assert len(got) == 1000, f"expected 2 full pages, got {len(got)}"
    assert calls == [0, 500, 1000], calls

    # A 4xx on the FIRST page is a real error and must still raise.
    client._get = lambda url, params: (_ for _ in ()).throw(ClientError("400"))
    try:
        list(client.iter_large_trades(2000))
        raise AssertionError("first-page ClientError should propagate")
    except ClientError:
        pass
    print("  api: stops cleanly at pagination cap, first-page errors still raise")


def resolved_gamma(cond):
    """Gamma /markets shape for a resolved market where index 1 won."""
    return {
        "conditionId": cond, "question": "Old market", "category": "Politics",
        "closed": True, "outcomePrices": '["0", "1"]',
        "endDate": "2026-01-01T00:00:00Z",
    }


def test_db_roundtrip_and_signals():
    raw_trade = {  # Data API /trades shape
        "transactionHash": "0xabc", "proxyWallet": "0xWALLET",
        "conditionId": "0xcond-open", "outcomeIndex": 1, "outcome": "Yes",
        "side": "BUY", "price": 0.12, "size": 100_000,
        "timestamp": 1_900_000_000, "title": "Will X happen?",
        "eventSlug": "will-x-happen", "pseudonym": "Test-Whale",
    }
    with tempfile.TemporaryDirectory() as tmp:
        con = db.connect(os.path.join(tmp, "t.db"))
        # History: wins on 8 DISTINCT markets -> 8 resolved positions.
        history = [dict(raw_trade, transactionHash=f"0xh{i}",
                        conditionId=f"0xcond{i}", timestamp=1_800_000_000 + i)
                   for i in range(8)]
        # Second fill on market 0 at a different price: must merge into ONE
        # position with a share-weighted entry, not count as a 9th bet.
        history.append(dict(raw_trade, transactionHash="0xh0b",
                            conditionId="0xcond0", price=0.10, size=100_000,
                            timestamp=1_800_000_100))
        added = db.upsert_trades(con, history + [raw_trade, raw_trade])
        assert added == 10, f"dedupe failed: {added}"
        for i in range(8):
            db.upsert_market(con, resolved_gamma(f"0xcond{i}"))

        positions = db.resolved_longshot_buys(con, CFG)
        assert len(positions) == 8 and all(r["won"] for r in positions)
        merged = [r for r in positions if r["condition_id"] == "0xcond0"][0]
        assert merged["fills"] == 2 and merged["cash"] == 22_000
        assert abs(merged["price"] - 0.11) < 1e-9  # (12k + 10k) / 200k shares

        cfg = Config(signal_window_days=10_000_000)  # huge window for fixed ts
        sigs = generate(con, cfg)
        assert len(sigs) == 1 and sigs[0].outcome == "Yes"
        assert sigs[0].smart_notional == 0.12 * 100_000
        print(f"  db+signals: dedupe ok, fill->position aggregation ok "
              f"(2 fills -> 1 bet @ {merged['price']:.2f}), "
              f"1 signal @ ${sigs[0].smart_notional:,.0f} smart notional")


def test_rank_orders_by_total_whale_notional():
    def raw(tx, wallet, cond, cash_at_10c, ts=1_900_000_000, outcome="Yes",
            outcome_index=1, event=None):
        return {
            "transactionHash": tx, "proxyWallet": wallet, "conditionId": cond,
            "outcomeIndex": outcome_index, "outcome": outcome, "side": "BUY",
            "price": 0.10, "size": cash_at_10c / 0.10, "timestamp": ts,
            "title": f"Market {cond}", "eventSlug": event or f"event-{cond}",
            "pseudonym": wallet,
        }

    with tempfile.TemporaryDirectory() as tmp:
        con = db.connect(os.path.join(tmp, "t.db"))
        # Smart-whale history: wins on 8 distinct resolved markets for whale-a.
        history = [raw(f"0xh{i}", "whale-a", f"0xres{i}", 12_000,
                       ts=1_800_000_000 + i) for i in range(8)]
        db.upsert_trades(con, history)
        for i in range(8):
            db.upsert_market(con, resolved_gamma(f"0xres{i}"))
        # Open bets: market B gets $90k across two whales, market A gets $50k
        # from the smart whale alone. whale-c also buys the OTHER side of B's
        # event (a hedge), and b/c have no other history (fresh wallets).
        db.upsert_trades(con, [
            raw("0xa1", "whale-a", "0xmktA", 50_000),
            raw("0xb1", "whale-b", "0xmktB", 60_000),
            raw("0xb2", "whale-c", "0xmktB", 30_000),
            raw("0xb3", "whale-c", "0xmktB2", 11_000, outcome="No",
                outcome_index=0, event="event-0xmktB"),
            # Clip accumulation: 3 x $4k fills cross the $10k position bar...
            raw("0xd1", "whale-d", "0xmktC", 4_000),
            raw("0xd2", "whale-d", "0xmktC", 4_000, ts=1_900_000_060),
            raw("0xd3", "whale-d", "0xmktC", 4_000, ts=1_900_000_120),
            # ...while a lone $4k punt stays below it.
            raw("0xe1", "whale-e", "0xmktD", 4_000),
        ])

        cfg = Config(signal_window_days=10_000_000)
        bets = rank_bets(con, cfg)
        assert [b.condition_id for b in bets][:2] == ["0xmktB", "0xmktA"], \
            [b.condition_id for b in bets]
        assert bets[0].total_notional == 90_000 and bets[0].n_whales == 2
        assert bets[0].smart_notional == 0          # b and c have no record
        assert bets[1].smart_notional == 50_000     # whale-a qualified
        assert bets[1].top_wallets[0][2] is True    # flagged smart

        # Insider-pattern flags: b and c are fresh; c hedged across the event.
        assert bets[0].fresh_notional == 90_000
        tags = {name: t for name, _, _, t in bets[0].top_wallets}
        assert tags["whale-b"] == "fresh"
        assert tags["whale-c"] == "fresh,hedged"
        assert bets[1].fresh_notional == 0          # whale-a has 9 fills of history

        # Position-level whale bar: clip accumulation counts, lone punt doesn't.
        by_cond = {b.condition_id: b for b in bets}
        assert "0xmktC" in by_cond and by_cond["0xmktC"].total_notional == 12_000
        assert by_cond["0xmktC"].n_trades == 3 and by_cond["0xmktC"].n_whales == 1
        assert "0xmktD" not in by_cond

        class StubClient:  # Gamma response for live (unresolved) markets
            def markets_by_condition_ids(self, ids):
                return [
                    {"conditionId": "0xmktB", "outcomePrices": '["0.82", "0.18"]'},
                    {"conditionId": "0xmktA", "outcomePrices": '["0.85", "0.15"]'},
                ]

        attach_live_prices(bets, StubClient())
        assert bets[0].current_price == 0.18        # outcome_index 1

        # EV layer: whale-a's record is 8/8 wins at 0.10 entries, so its
        # shrunken alpha = (8+3)/(0.8+3) ~= 2.895 and the implied true prob of
        # its open 0.10 entry is ~0.29; at the live 0.15 price EV ~= +93%.
        assert bets[0].q_smart is None              # no smart money on mktB
        assert bets[0].expected_value() is None
        assert abs(bets[1].q_smart - 0.2895) < 0.01, bets[1].q_smart
        ev = bets[1].expected_value()
        assert 0.85 < ev < 1.0, f"expected ~+93% EV, got {ev}"

        md = build_markdown(bets[:10], cfg, now_ts=1_900_000_500)
        html_out = build_html(bets[:10], cfg, now_ts=1_900_000_500)
        assert "| 1 | [Market 0xmktB" in md and "$90,000" in md
        assert "0.18 (+0.08)" in md                 # live drift in the board
        assert "<table>" in html_out and "$90,000" in html_out
        print(f"  rank: order by total notional ok "
              f"(${bets[0].total_notional:,.0f} > ${bets[1].total_notional:,.0f}), "
              f"smart split ok, live price attach ok "
              f"(entry {bets[0].weighted_entry:.2f} -> now {bets[0].current_price:.2f}), "
              f"md+html report ok")


if __name__ == "__main__":
    for fn in (test_scoring_separates_skill, test_backtest_walk_forward,
               test_pagination_cap_stops_cleanly,
               test_db_roundtrip_and_signals, test_rank_orders_by_total_whale_notional):
        print(f"{fn.__name__} ...")
        fn()
    print("\nall smoke tests passed")
